"""Content strategist — deterministic helpers for the strategist agent.

The agent does the writing. This module owns the deterministic boundary
work: prefetching the source article into clean text, slug generation,
reading-time estimation, and validation of the draft JSON the agent
returns.

CLI usage:
    python -m content_engine.strategist prefetch --url <url>
    python -m content_engine.strategist validate --draft path/to/draft.json
    python -m content_engine.strategist slug "Some Headline Goes Here"

Library usage:
    from content_engine.strategist import (
        prefetch_article, slugify, reading_time_minutes, validate_draft,
    )
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


USER_AGENT = "content-engine/0.1 (+https://github.com/anthropics/claude-code)"
FETCH_TIMEOUT_SECONDS = 20

# SEO hard limits drawn from current Google snippet rendering. Sources rot,
# so these are not guarantees — they are the limits the strategist agent
# is told to respect, and validate_draft enforces.
HEADLINE_MAX = 60
META_DESCRIPTION_MAX = 155
SLUG_MAX = 60
KEYWORDS_MIN = 3
KEYWORDS_MAX = 5
ALLOWED_SCHEMA_TYPES = {"Article", "NewsArticle", "BlogPosting"}

# Average reading speed for online English prose. Conservative; enough for
# a "5 min read" badge that doesn't lie to skim-readers.
WORDS_PER_MINUTE = 230


@dataclass
class Issue:
    """One validation finding. `level='error'` blocks publish; warnings inform."""

    level: str  # "error" | "warning"
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "field": self.field, "message": self.message}


# --- Slug generation -------------------------------------------------------


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SLUG_EDGES = re.compile(r"^-+|-+$")


def slugify(text: str, max_length: int = SLUG_MAX) -> str:
    """Convert arbitrary text into a URL-safe lowercase slug.

    - Unicode-normalized (NFKD) so accented characters fold to ASCII.
    - Non-alphanumeric runs collapse to a single hyphen.
    - Trimmed at word boundaries when over max_length to avoid mid-word cuts.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    hyphenated = _SLUG_STRIP.sub("-", lowered)
    trimmed = _SLUG_EDGES.sub("", hyphenated)
    if len(trimmed) <= max_length:
        return trimmed
    # Cut to max_length, then back off to the last hyphen so we don't
    # truncate mid-word (which makes slugs look broken).
    cut = trimmed[:max_length]
    last_hyphen = cut.rfind("-")
    if last_hyphen >= max_length // 2:
        cut = cut[:last_hyphen]
    return _SLUG_EDGES.sub("", cut)


# --- Reading time ----------------------------------------------------------


_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_markdown_for_count(md: str) -> str:
    """Reduce markdown to roughly the prose a reader actually consumes."""
    md = _FENCE_RE.sub(" ", md)
    md = _INLINE_CODE_RE.sub(" ", md)
    md = _IMAGE_RE.sub(" ", md)
    md = _LINK_RE.sub(r"\1", md)  # keep anchor text, drop URL
    md = _HTML_TAG_RE.sub(" ", md)
    return md


def reading_time_minutes(markdown: str, wpm: int = WORDS_PER_MINUTE) -> int:
    """Estimate reading time, rounded up to the nearest minute (min 1)."""
    if not markdown:
        return 1
    prose = _strip_markdown_for_count(markdown)
    words = re.findall(r"\b[\w'-]+\b", prose)
    minutes = (len(words) + wpm - 1) // wpm
    return max(1, minutes)


# --- Source-article prefetch ----------------------------------------------


_DROP_TAGS = ("script", "style", "noscript", "nav", "footer", "aside", "form")


def prefetch_article(url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Fetch and lightly clean a news URL into structured data the agent can use.

    Returns a dict with keys: url, status, title, meta_description, byline,
    publish_date, text. On failure, returns {"url": url, "status": "error",
    "error": "..."} so the caller can decide what to do.
    """
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )
        resp.raise_for_status()
    except requests.RequestException as ex:
        return {"url": url, "status": "error", "error": f"{ex.__class__.__name__}: {ex}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else "") or ""
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""

    meta_desc = ""
    for sel in [
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ]:
        tag = soup.find("meta", attrs=sel)
        if tag and tag.get("content"):
            meta_desc = tag["content"].strip()
            break

    byline = ""
    author = soup.find("meta", attrs={"name": "author"})
    if author and author.get("content"):
        byline = author["content"].strip()
    if not byline:
        byline_tag = soup.find(attrs={"rel": "author"})
        if byline_tag:
            byline = byline_tag.get_text(strip=True)

    publish_date = ""
    for sel in [
        {"property": "article:published_time"},
        {"name": "pubdate"},
        {"itemprop": "datePublished"},
    ]:
        tag = soup.find("meta", attrs=sel)
        if tag and tag.get("content"):
            publish_date = tag["content"].strip()
            break

    article_tag = soup.find("article") or soup.find("main") or soup.body
    if article_tag is None:
        text = ""
    else:
        # Join paragraph-ish tags with blank lines so the agent can see
        # structure without us guessing at semantic boundaries.
        chunks = []
        for el in article_tag.find_all(["h1", "h2", "h3", "p", "li"]):
            txt = el.get_text(" ", strip=True)
            if txt:
                chunks.append(txt)
        text = "\n\n".join(chunks)

    return {
        "url": url,
        "status": "ok",
        "title": title,
        "meta_description": meta_desc,
        "byline": byline,
        "publish_date": publish_date,
        "text": text[:20000],  # cap so prompt budgets don't blow up
    }


# --- Draft validation -----------------------------------------------------


_REQUIRED_FIELDS = (
    "headline",
    "meta_description",
    "slug",
    "target_keywords",
    "article_body",
    "schema_type",
)

_SLUG_VALID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_H1_RE = re.compile(r"^#\s", re.MULTILINE)
_H2_RE = re.compile(r"^##\s", re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{1,6})\s", re.MULTILINE)


def validate_draft(draft: dict[str, Any]) -> list[Issue]:
    """Run hard + soft checks on a strategist draft. Returns a list of Issues.

    Errors mean the draft is not ready to ship. Warnings flag things a
    human reviewer should look at but do not block automated pipelines.
    """
    issues: list[Issue] = []

    if not isinstance(draft, dict):
        return [Issue("error", "_root", "Draft must be a JSON object.")]

    for field in _REQUIRED_FIELDS:
        if field not in draft:
            issues.append(Issue("error", field, "Required field is missing."))
    # If anything required is missing, downstream checks may KeyError; bail.
    if any(i.level == "error" for i in issues):
        return issues

    headline = draft["headline"]
    if not isinstance(headline, str) or not headline.strip():
        issues.append(Issue("error", "headline", "Must be a non-empty string."))
    elif len(headline) > HEADLINE_MAX:
        issues.append(
            Issue("error", "headline", f"Length {len(headline)} exceeds {HEADLINE_MAX} chars.")
        )

    meta = draft["meta_description"]
    if not isinstance(meta, str) or not meta.strip():
        issues.append(Issue("error", "meta_description", "Must be a non-empty string."))
    elif len(meta) > META_DESCRIPTION_MAX:
        issues.append(
            Issue(
                "error",
                "meta_description",
                f"Length {len(meta)} exceeds {META_DESCRIPTION_MAX} chars.",
            )
        )

    slug = draft["slug"]
    if not isinstance(slug, str) or not slug:
        issues.append(Issue("error", "slug", "Must be a non-empty string."))
    elif not _SLUG_VALID_RE.match(slug):
        issues.append(
            Issue(
                "error",
                "slug",
                "Must be lowercase alphanumeric + single hyphens (no leading/trailing).",
            )
        )
    elif len(slug) > SLUG_MAX:
        issues.append(Issue("error", "slug", f"Length {len(slug)} exceeds {SLUG_MAX}."))

    keywords = draft["target_keywords"]
    if not isinstance(keywords, list) or not all(isinstance(k, str) and k.strip() for k in keywords):
        issues.append(Issue("error", "target_keywords", "Must be a list of non-empty strings."))
    else:
        if not (KEYWORDS_MIN <= len(keywords) <= KEYWORDS_MAX):
            issues.append(
                Issue(
                    "error",
                    "target_keywords",
                    f"Need {KEYWORDS_MIN}-{KEYWORDS_MAX} keywords, got {len(keywords)}.",
                )
            )

    body = draft["article_body"]
    if not isinstance(body, str) or not body.strip():
        issues.append(Issue("error", "article_body", "Must be non-empty markdown."))
    else:
        if _H1_RE.search(body):
            issues.append(
                Issue(
                    "error",
                    "article_body",
                    "Body must not contain H1 — the headline becomes the H1 at render time.",
                )
            )
        h2_count = len(_H2_RE.findall(body))
        if h2_count < 2:
            issues.append(
                Issue(
                    "warning",
                    "article_body",
                    f"Only {h2_count} H2 section(s). Aim for 2-4 for readability/SEO.",
                )
            )
        elif h2_count > 6:
            issues.append(
                Issue(
                    "warning",
                    "article_body",
                    f"{h2_count} H2 sections is a lot — consider consolidating.",
                )
            )
        # Each declared keyword should appear at least once in the body.
        if isinstance(keywords, list):
            body_lower = body.lower()
            for kw in keywords:
                if isinstance(kw, str) and kw.strip():
                    if kw.lower() not in body_lower:
                        issues.append(
                            Issue(
                                "warning",
                                "article_body",
                                f"Target keyword {kw!r} does not appear in the body.",
                            )
                        )

    schema_type = draft["schema_type"]
    if schema_type not in ALLOWED_SCHEMA_TYPES:
        issues.append(
            Issue(
                "error",
                "schema_type",
                f"Must be one of {sorted(ALLOWED_SCHEMA_TYPES)}, got {schema_type!r}.",
            )
        )

    # estimated_reading_time is optional in the JSON; compute and warn on drift.
    declared_rt = draft.get("estimated_reading_time")
    if isinstance(body, str) and body.strip():
        actual_rt = reading_time_minutes(body)
        if isinstance(declared_rt, int) and declared_rt > 0:
            if abs(declared_rt - actual_rt) > 2:
                issues.append(
                    Issue(
                        "warning",
                        "estimated_reading_time",
                        f"Declared {declared_rt} min but body computes to {actual_rt} min.",
                    )
                )

    links = draft.get("suggested_internal_links")
    if links is not None:
        if not isinstance(links, list):
            issues.append(Issue("error", "suggested_internal_links", "Must be a list."))
        else:
            for i, link in enumerate(links):
                if not isinstance(link, dict):
                    issues.append(
                        Issue("error", f"suggested_internal_links[{i}]", "Must be an object.")
                    )
                    continue
                for key in ("anchor_text", "target"):
                    if not link.get(key):
                        issues.append(
                            Issue(
                                "error",
                                f"suggested_internal_links[{i}].{key}",
                                "Required and must be non-empty.",
                            )
                        )

    return issues


# --- CLI -------------------------------------------------------------------


def _cmd_prefetch(args: argparse.Namespace) -> int:
    out = prefetch_article(args.url)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if out.get("status") == "ok" else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.draft)
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        print(f"error: draft is not valid JSON: {ex}", file=sys.stderr)
        return 2

    issues = validate_draft(draft)
    payload = {
        "ok": not any(i.level == "error" for i in issues),
        "issues": [i.as_dict() for i in issues],
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


def _cmd_slug(args: argparse.Namespace) -> int:
    print(slugify(args.text))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="content_engine.strategist")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("prefetch", help="Fetch and clean a source article URL.")
    p_pre.add_argument("--url", required=True)
    p_pre.set_defaults(func=_cmd_prefetch)

    p_val = sub.add_parser("validate", help="Validate a strategist draft JSON file.")
    p_val.add_argument("--draft", required=True)
    p_val.set_defaults(func=_cmd_validate)

    p_slug = sub.add_parser("slug", help="Generate a URL-safe slug from text.")
    p_slug.add_argument("text")
    p_slug.set_defaults(func=_cmd_slug)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
