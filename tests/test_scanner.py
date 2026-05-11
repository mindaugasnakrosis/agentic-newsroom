"""Tests for the news scanner module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_engine.scanner import (
    Candidate,
    _domain,
    _keyword_match,
    _seo_potential,
    _source_tier_score,
    load_config,
    post_to_slack,
    scan,
    scan_local_feed,
)


FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_RSS = FIXTURES / "sample-rss.xml"


@pytest.fixture
def fintech_config() -> dict:
    return {
        "company": {
            "name": "Acme Fintech",
            "industry": "financial technology",
            "expertise_areas": ["SMB lending"],
        },
        "content": {
            "keywords": [
                "interest rates",
                "SBA loans",
                "small business",
                "Fed",
                "working capital",
                "business credit",
            ],
            "sources": {
                "rss_feeds": [str(SAMPLE_RSS)],
                "web_search_queries": [],
            },
            "max_articles_per_run": 5,
            "min_relevance_score": 0,
            # Wide window so the fixture's dated-2026 entries always match.
            "date_range_days": 365 * 5,
        },
    }


def test_domain_normalization():
    assert _domain("https://www.bloomberg.com/news/x") == "bloomberg.com"
    assert _domain("https://feeds.bloomberg.com/markets/news.rss") == "feeds.bloomberg.com"
    assert _domain("not a url") == ""


def test_source_tier_scoring():
    assert _source_tier_score("https://www.bloomberg.com/x") == 20
    assert _source_tier_score("https://feeds.bloomberg.com/x") == 20
    assert _source_tier_score("https://www.cnbc.com/x") == 12
    assert _source_tier_score("https://random-blog.example.com/x") == 6


def test_keyword_match_is_case_insensitive():
    matches = _keyword_match(
        "The Federal Reserve cut interest rates today",
        ["interest rates", "SBA loans", "Fed"],
    )
    assert "interest rates" in matches
    # Title text doesn't contain "Fed" as a standalone token but does match
    # substring "Fed" in "Federal" — keyword matching is substring-based.
    assert "Fed" in matches
    assert "SBA loans" not in matches


def test_seo_potential_buckets():
    assert _seo_potential(80) == "high"
    assert _seo_potential(60) == "medium"
    assert _seo_potential(20) == "low"


def test_load_config_round_trip(tmp_path: Path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("company:\n  name: Test\ncontent:\n  keywords: [foo]\n")
    loaded = load_config(cfg_path)
    assert loaded["company"]["name"] == "Test"
    assert loaded["content"]["keywords"] == ["foo"]


def test_load_config_rejects_non_mapping(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        load_config(bad)


def test_scan_local_feed_ranks_relevant_above_irrelevant(fintech_config):
    items = scan_local_feed(SAMPLE_RSS, fintech_config)
    assert len(items) >= 2
    # Fed rate cut item should rank above the unrelated tech buyback item.
    titles = [c.title for c in items]
    fed_idx = next(i for i, t in enumerate(titles) if "Fed cuts" in t)
    buyback_idx = next(i for i, t in enumerate(titles) if "buyback" in t.lower())
    assert fed_idx < buyback_idx
    # And the Fed item should have a non-trivial score.
    fed = items[fed_idx]
    assert fed.relevance_score >= 30
    assert "interest rates" in fed.matched_keywords


def test_scan_drops_items_outside_date_window(fintech_config):
    fintech_config["content"]["date_range_days"] = 7
    # The fixture has one item from Jan 2025 — it must be filtered out.
    items = scan_local_feed(SAMPLE_RSS, fintech_config)
    titles = [c.title for c in items]
    assert not any("Old news" in t for t in titles)


def test_scan_respects_min_relevance_score(fintech_config):
    fintech_config["content"]["min_relevance_score"] = 95  # impossibly high
    items = scan(fintech_config)
    assert items == []


class _StubResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


def test_post_to_slack_sends_expected_payload(monkeypatch):
    calls: list[dict] = []

    def fake_post(url: str, json: dict, timeout: int):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _StubResponse(200)

    monkeypatch.setattr("content_engine.scanner.requests.post", fake_post)

    cands = [
        Candidate(
            title="Fed cuts rates",
            source="Reuters",
            url="https://reuters.example/x",
            published_date="2026-05-06",
            summary="",
            relevance_score=78,
            seo_potential="high",
            suggested_angle="",
        )
    ]
    ok = post_to_slack("https://hooks.slack.com/services/X/Y/Z", cands, config_name="fintech")
    assert ok is True
    assert len(calls) == 1
    assert calls[0]["url"] == "https://hooks.slack.com/services/X/Y/Z"
    payload_text = calls[0]["json"]["text"]
    assert "fintech" in payload_text
    assert "78" in payload_text  # score appears in the digest
    assert "Fed cuts rates" in payload_text
    assert "reuters.example/x" in payload_text


def test_post_to_slack_handles_empty_candidates(monkeypatch):
    captured: list[dict] = []

    def fake_post(url, json, timeout):
        captured.append(json)
        return _StubResponse(200)

    monkeypatch.setattr("content_engine.scanner.requests.post", fake_post)
    ok = post_to_slack("https://hooks.slack.com/services/X/Y/Z", [], config_name="fintech")
    assert ok is True
    assert "no candidates" in captured[0]["text"].lower()


def test_post_to_slack_returns_false_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "content_engine.scanner.requests.post",
        lambda *a, **kw: _StubResponse(500),
    )
    ok = post_to_slack("https://hooks.slack.com/services/X/Y/Z", [], config_name="x")
    assert ok is False


def test_post_to_slack_swallows_network_errors(monkeypatch):
    import requests

    def boom(*args, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr("content_engine.scanner.requests.post", boom)
    # Must not raise; must return False.
    ok = post_to_slack("https://hooks.slack.com/services/X/Y/Z", [], config_name="x")
    assert ok is False


def test_candidate_dataclass_fields():
    c = Candidate(
        title="t",
        source="s",
        url="https://example.com",
        published_date=None,
        summary="x",
        relevance_score=42,
        seo_potential="low",
        suggested_angle="",
    )
    # suggested_angle is filled by the agent layer; default empty is fine.
    assert c.suggested_angle == ""
    assert c.matched_keywords == []
