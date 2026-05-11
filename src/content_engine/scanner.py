"""News scanner — fetches RSS feeds, filters by config, scores by relevance.

This module is the deterministic half of the news-scanner agent. The agent
delegates feed parsing here and then layers judgment on top of the scored
candidates this module returns.

CLI usage:
    python -m content_engine.scanner --config config/examples/fintech.yaml

Library usage:
    from content_engine.scanner import scan
    items = scan(config_dict)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import feedparser
import requests
import yaml


# A polite UA. Some feeds (Yahoo, Bloomberg) reject the default urllib UA.
USER_AGENT = "content-engine/0.1 (+https://github.com/anthropics/claude-code)"
FETCH_TIMEOUT_SECONDS = 15


# Authority tiers for source scoring. Match is on hostname suffix.
TIER_1_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "nytimes.com",
    "economist.com",
    "federalreserve.gov",
    "treasury.gov",
    "sec.gov",
}
TIER_2_DOMAINS = {
    "yahoo.com",
    "cnbc.com",
    "marketwatch.com",
    "axios.com",
    "techcrunch.com",
    "theverge.com",
    "arstechnica.com",
    "forbes.com",
    "businessinsider.com",
}


@dataclass
class Candidate:
    """A single scored content opportunity."""

    title: str
    source: str
    url: str
    published_date: str | None
    summary: str
    relevance_score: int
    seo_potential: str
    suggested_angle: str
    matched_keywords: list[str] = field(default_factory=list)


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config from disk."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} must be a YAML mapping at the root.")
    return data


def _parse_published(entry: Any) -> datetime | None:
    """Best-effort parse of an entry's published date into a UTC datetime."""
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            try:
                return datetime(*struct[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.lower().lstrip("www.")


def _source_tier_score(url: str) -> int:
    host = _domain(url)
    for tier1 in TIER_1_DOMAINS:
        if host == tier1 or host.endswith("." + tier1):
            return 20
    for tier2 in TIER_2_DOMAINS:
        if host == tier2 or host.endswith("." + tier2):
            return 12
    return 6


def _recency_score(published: datetime | None) -> int:
    if published is None:
        return 0
    now = datetime.now(timezone.utc)
    age = now - published
    if age <= timedelta(days=1):
        return 20
    if age <= timedelta(days=3):
        return 15
    if age <= timedelta(days=7):
        return 10
    return 0


def _keyword_match(text: str, keywords: Iterable[str]) -> list[str]:
    lower = text.lower()
    return [kw for kw in keywords if kw.lower() in lower]


def _seo_potential(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _score_entry(
    entry: Any,
    feed_title: str,
    keywords: list[str],
    date_range_days: int,
) -> Candidate | None:
    """Score one feed entry. Returns None if it should be dropped."""
    url = getattr(entry, "link", None)
    title = getattr(entry, "title", "") or ""
    if not url or not title:
        return None

    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    published = _parse_published(entry)

    if published is not None and date_range_days > 0:
        if datetime.now(timezone.utc) - published > timedelta(days=date_range_days):
            return None

    title_matches = _keyword_match(title, keywords)
    summary_matches = _keyword_match(summary, keywords)
    all_matched = sorted(set(title_matches) | set(summary_matches))

    keyword_score = min(40, 8 * len(title_matches) + 4 * len(summary_matches))
    source_score = _source_tier_score(url)
    recency_score = _recency_score(published)
    # SEO potential is a heuristic on title length + keyword density.
    # Short, keyword-rich titles tend to win reactive search demand.
    seo_raw = min(20, 5 * len(all_matched) + (5 if 30 <= len(title) <= 70 else 0))

    total = min(100, keyword_score + source_score + recency_score + seo_raw)

    source_name = feed_title or _domain(url) or "unknown"
    published_str = published.date().isoformat() if published else None

    return Candidate(
        title=title.strip(),
        source=source_name,
        url=url,
        published_date=published_str,
        summary=summary.strip()[:500],
        relevance_score=total,
        seo_potential=_seo_potential(total),
        suggested_angle="",  # Filled by the agent layer, not here.
        matched_keywords=all_matched,
    )


def _fetch_feed(url: str) -> Any:
    """Fetch a feed URL with a real HTTP client (certifi-backed TLS) and hand
    the body to feedparser. Returns the parsed feed, or an empty stub on
    failure. Network errors are swallowed by design — a single broken feed
    must never sink the whole scan.

    For non-HTTP schemes (`file://`, bare paths) we delegate straight to
    feedparser, which handles them natively. This keeps offline development
    and tests trivial without a fake HTTP server.
    """
    if not url.startswith(("http://", "https://")):
        return feedparser.parse(url)
    try:
        resp = requests.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"},
        )
        resp.raise_for_status()
    except requests.RequestException:
        return feedparser.parse(b"")
    return feedparser.parse(resp.content)


def scan(config: dict[str, Any]) -> list[Candidate]:
    """Run a full scan over the config and return ranked Candidates.

    The agent layer is expected to fill in `suggested_angle` and may re-rank
    or trim further. This function never invents data.
    """
    content_cfg = config.get("content", {}) or {}
    keywords: list[str] = list(content_cfg.get("keywords") or [])
    feeds: list[str] = list((content_cfg.get("sources") or {}).get("rss_feeds") or [])
    max_items: int = int(content_cfg.get("max_articles_per_run") or 10)
    min_score: int = int(content_cfg.get("min_relevance_score") or 0)
    date_range_days: int = int(content_cfg.get("date_range_days") or 7)

    if not feeds:
        return []

    candidates: list[Candidate] = []
    seen_urls: set[str] = set()

    for feed_url in feeds:
        parsed = _fetch_feed(feed_url)
        feed_title = getattr(getattr(parsed, "feed", None), "title", "") or ""
        for entry in getattr(parsed, "entries", []) or []:
            cand = _score_entry(entry, feed_title, keywords, date_range_days)
            if cand is None:
                continue
            if cand.url in seen_urls:
                continue
            if cand.relevance_score < min_score:
                continue
            seen_urls.add(cand.url)
            candidates.append(cand)

    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    return candidates[:max_items]


def scan_local_feed(path: str | Path, config: dict[str, Any]) -> list[Candidate]:
    """Scan a local RSS file (used by tests and offline development)."""
    content_cfg = config.get("content", {}) or {}
    keywords = list(content_cfg.get("keywords") or [])
    date_range_days = int(content_cfg.get("date_range_days") or 7)

    parsed = feedparser.parse(str(path))
    feed_title = getattr(getattr(parsed, "feed", None), "title", "") or ""
    out: list[Candidate] = []
    for entry in getattr(parsed, "entries", []) or []:
        cand = _score_entry(entry, feed_title, keywords, date_range_days)
        if cand is not None:
            out.append(cand)
    out.sort(key=lambda c: c.relevance_score, reverse=True)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="content_engine.scanner",
        description="Scan RSS feeds for content opportunities.",
    )
    parser.add_argument("--config", required=True, help="Path to a YAML config.")
    parser.add_argument(
        "--output",
        choices=["json", "table"],
        default="json",
        help="Output format. Default: json (machine-readable).",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    candidates = scan(config)

    if args.output == "json":
        json.dump([asdict(c) for c in candidates], sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for c in candidates:
            print(f"[{c.relevance_score:>3}] {c.title}")
            print(f"        {c.source}  {c.published_date or '?'}  {c.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
