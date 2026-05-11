"""Tests for the content strategist module — slugify, reading time, validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_engine.strategist import (
    HEADLINE_MAX,
    META_DESCRIPTION_MAX,
    SLUG_MAX,
    Issue,
    reading_time_minutes,
    slugify,
    validate_draft,
)


# --- slugify --------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Hello World", "hello-world"),
        ("  Multiple   spaces  ", "multiple-spaces"),
        ("Symbols!@#$%^&*()stripped", "symbols-stripped"),
        ("Café résumé naïve", "cafe-resume-naive"),
        ("Already-good-slug", "already-good-slug"),
        ("Trailing--hyphens---", "trailing-hyphens"),
        ("---Leading and trailing---", "leading-and-trailing"),
        ("", ""),
    ],
)
def test_slugify_normalizes(raw, expected):
    assert slugify(raw) == expected


def test_slugify_respects_max_length_at_word_boundary():
    headline = "Federal Reserve Cuts Interest Rates Twenty Five Basis Points Today"
    s = slugify(headline)
    assert len(s) <= SLUG_MAX
    # Should not end mid-word.
    assert not s.endswith("-")
    # Cut should land on a hyphen boundary, so no truncated word fragment.
    assert "interes" not in s or "interest" in s


def test_slugify_handles_non_ascii_only_input():
    # All-non-ASCII input collapses to empty, then slugify returns "".
    assert slugify("中文标题") == ""


# --- reading time ---------------------------------------------------------


def test_reading_time_minimum_is_one_minute():
    assert reading_time_minutes("hello") == 1
    assert reading_time_minutes("") == 1


def test_reading_time_scales_with_word_count():
    # ~460 words @ 230 wpm = 2 minutes.
    body = ("word " * 460).strip()
    assert reading_time_minutes(body) == 2


def test_reading_time_strips_code_blocks():
    code_heavy = "Intro paragraph.\n\n```\n" + ("code " * 1000) + "```\n\nOutro."
    # Without stripping, this would be ~5 min. With stripping, just intro+outro.
    assert reading_time_minutes(code_heavy) == 1


def test_reading_time_keeps_link_anchor_text():
    body = "Here is [a useful link](https://example.com/super/long/path) in prose. " * 50
    # Anchor text "a useful link in prose" * 50 should still produce a real count.
    assert reading_time_minutes(body) >= 1


# --- validate_draft -------------------------------------------------------


def _good_draft() -> dict:
    body = (
        "Intro paragraph that mentions interest rates and SBA loans for context.\n\n"
        "## Section one\n\nProse with primary keyword small business loans.\n\n"
        "## Section two\n\nMore analysis with the working capital angle.\n\n"
        "## Takeaways\n\nClosing CTA paragraph.\n"
    )
    return {
        "headline": "What the Fed Cut Means for SMB Borrowers",
        "meta_description": (
            "The Fed's 25bp cut won't change small business loans overnight — "
            "here's the realistic timeline and what to do now."
        ),
        "slug": "fed-cut-smb-borrowers",
        "target_keywords": [
            "interest rates",
            "small business loans",
            "SBA loans",
            "working capital",
        ],
        "article_body": body,
        "estimated_reading_time": 1,
        "suggested_internal_links": [
            {
                "anchor_text": "working capital lines",
                "target": "/products/credit-line",
                "reason": "Reader will want to see the product after analysis.",
            }
        ],
        "schema_type": "Article",
        "source_attribution": {
            "url": "https://example.com/news",
            "title": "Fed cuts rates",
            "publisher": "Example Wire",
        },
    }


def test_good_draft_passes_with_no_errors():
    issues = validate_draft(_good_draft())
    errors = [i for i in issues if i.level == "error"]
    assert errors == [], errors


def test_missing_required_fields_are_errors():
    issues = validate_draft({"headline": "Hi"})
    fields = {i.field for i in issues if i.level == "error"}
    assert "meta_description" in fields
    assert "slug" in fields
    assert "article_body" in fields
    assert "schema_type" in fields


def test_headline_too_long_is_error():
    d = _good_draft()
    d["headline"] = "x" * (HEADLINE_MAX + 1)
    errs = [i for i in validate_draft(d) if i.level == "error" and i.field == "headline"]
    assert errs


def test_meta_description_too_long_is_error():
    d = _good_draft()
    d["meta_description"] = "x" * (META_DESCRIPTION_MAX + 1)
    errs = [i for i in validate_draft(d) if i.level == "error" and i.field == "meta_description"]
    assert errs


def test_invalid_slug_format_is_error():
    d = _good_draft()
    d["slug"] = "Not A Valid Slug!"
    errs = [i for i in validate_draft(d) if i.level == "error" and i.field == "slug"]
    assert errs


def test_too_few_keywords_is_error():
    d = _good_draft()
    d["target_keywords"] = ["only-one"]
    errs = [i for i in validate_draft(d) if i.level == "error" and i.field == "target_keywords"]
    assert errs


def test_h1_in_body_is_error():
    d = _good_draft()
    d["article_body"] = "# This Is An H1\n\n## Section\n\nText.\n"
    errs = [i for i in validate_draft(d) if i.level == "error" and i.field == "article_body"]
    assert any("H1" in e.message for e in errs)


def test_keyword_missing_from_body_is_warning_not_error():
    d = _good_draft()
    d["target_keywords"] = [
        "interest rates",
        "small business loans",
        "completely-absent-phrase",
    ]
    issues = validate_draft(d)
    warnings = [i for i in issues if i.level == "warning" and "completely-absent-phrase" in i.message]
    errors = [i for i in issues if i.level == "error"]
    assert warnings
    assert errors == []


def test_invalid_schema_type_is_error():
    d = _good_draft()
    d["schema_type"] = "FAQPage"  # not in allowed set
    errs = [i for i in validate_draft(d) if i.level == "error" and i.field == "schema_type"]
    assert errs


def test_internal_link_missing_anchor_is_error():
    d = _good_draft()
    d["suggested_internal_links"] = [{"target": "/x"}]
    errs = [i for i in validate_draft(d) if i.level == "error" and "anchor_text" in i.field]
    assert errs


def test_reading_time_drift_is_warning():
    d = _good_draft()
    d["estimated_reading_time"] = 30  # body is ~1 min
    warns = [
        i for i in validate_draft(d) if i.level == "warning" and i.field == "estimated_reading_time"
    ]
    assert warns


def test_validate_draft_rejects_non_object():
    issues = validate_draft(["not", "an", "object"])  # type: ignore[arg-type]
    assert any(i.level == "error" for i in issues)


# --- CLI smoke test -------------------------------------------------------


def test_validate_cli_writes_json_and_exits_nonzero_on_errors(tmp_path: Path):
    from content_engine.strategist import main

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"headline": "x"}))
    rc = main(["validate", "--draft", str(bad)])
    assert rc == 1


def test_validate_cli_returns_zero_on_clean_draft(tmp_path: Path):
    from content_engine.strategist import main

    good = tmp_path / "good.json"
    good.write_text(json.dumps(_good_draft()))
    rc = main(["validate", "--draft", str(good)])
    assert rc == 0


def test_slug_cli(capsys):
    from content_engine.strategist import main

    rc = main(["slug", "Hello, World!"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == "hello-world"
