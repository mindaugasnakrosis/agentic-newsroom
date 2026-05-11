"""Tests for the publisher — frontmatter, JSON-LD, MDX render, validation, asset copy."""

from __future__ import annotations

import json
from pathlib import Path

import frontmatter
import pytest
import yaml

from content_engine.publisher import (
    _has_cta,
    _public_image_path,
    build_frontmatter,
    build_jsonld,
    render_article,
    render_mdx,
    validate_mdx,
)


def _good_draft() -> dict:
    body = (
        "Intro paragraph that mentions interest rates and SBA loans for context.\n\n"
        "## What changed\n\nProse with primary keyword small business loans and working capital.\n\n"
        "## What this means for SMB borrowers\n\nMore analysis with concrete numbers.\n\n"
        "## Takeaways\n\nClosing analysis paragraph.\n"
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


def _config(out_dir: Path, image_dir: Path) -> dict:
    return {
        "company": {
            "name": "Acme Fintech",
            "industry": "fintech",
            "products": ["small business loans"],
            "audience": "SMBs",
            "tone": "expert",
            "expertise_areas": ["SMB lending"],
            "cta_url": "https://acmefintech.com/apply",
            "cta_text": "See your rate in 60 seconds",
            "brand_colors": {"primary": "#000000", "accent": "#ff0000"},
            "logo_path": None,
        },
        "content": {"keywords": [], "sources": {"rss_feeds": []}},
        "publishing": {
            "output_dir": str(out_dir),
            "format": "mdx",
            "git": {"enabled": False, "branch_prefix": "content/", "auto_pr": False},
            "nextjs": {
                "content_dir": str(out_dir),
                "image_dir": str(image_dir),
            },
        },
    }


# --- Public image path mapping -------------------------------------------


def test_public_image_path_strips_public_prefix():
    assert _public_image_path("foo.png", "public/images/blog") == "/images/blog/foo.png"


def test_public_image_path_leaves_non_public_root_alone():
    assert _public_image_path("foo.png", "src/static/blog") == "/src/static/blog/foo.png"


# --- CTA detection --------------------------------------------------------


def test_has_cta_detects_url_in_body():
    body = "Some text.\n\n[Apply now](https://acmefintech.com/apply)"
    assert _has_cta(body, "https://acmefintech.com/apply", "Apply now")


def test_has_cta_detects_text_only():
    body = "Some text. See your rate in 60 seconds. End."
    assert _has_cta(body, "https://acmefintech.com/apply", "See your rate in 60 seconds")


def test_has_cta_returns_false_when_absent():
    body = "No CTA here."
    assert not _has_cta(body, "https://acmefintech.com/apply", "See your rate")


# --- JSON-LD --------------------------------------------------------------


def test_jsonld_required_fields(tmp_path: Path):
    draft = _good_draft()
    cfg = _config(tmp_path / "out", tmp_path / "images")
    ld = build_jsonld(draft, cfg, og_image_public_path="/images/blog/og.png", publish_date="2026-05-07")
    assert ld["@context"] == "https://schema.org"
    assert ld["@type"] == "Article"
    assert ld["headline"] == draft["headline"]
    assert ld["description"] == draft["meta_description"]
    assert ld["datePublished"] == "2026-05-07"
    assert ld["author"]["name"] == "Acme Fintech"
    assert ld["author"]["url"] == "https://acmefintech.com"  # derived from cta_url
    assert ld["publisher"]["name"] == "Acme Fintech"
    assert "logo" not in ld["publisher"]  # no logo_path set
    assert ld["image"] == "/images/blog/og.png"
    assert ld["mainEntityOfPage"]["@id"].endswith("/blog/fed-cut-smb-borrowers")
    assert ld["isBasedOn"]["url"] == "https://example.com/news"


def test_jsonld_includes_logo_when_configured(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    cfg["company"]["logo_path"] = "/images/logo.svg"
    ld = build_jsonld(_good_draft(), cfg, og_image_public_path=None, publish_date="2026-05-07")
    assert ld["publisher"]["logo"]["url"] == "/images/logo.svg"
    assert "image" not in ld  # no og image was provided


def test_jsonld_omits_isbasedon_when_no_source(tmp_path: Path):
    draft = _good_draft()
    draft.pop("source_attribution")
    cfg = _config(tmp_path / "out", tmp_path / "images")
    ld = build_jsonld(draft, cfg, og_image_public_path=None, publish_date="2026-05-07")
    assert "isBasedOn" not in ld


# --- Frontmatter ----------------------------------------------------------


def test_frontmatter_uses_strategist_reading_time_when_provided(tmp_path: Path):
    draft = _good_draft()
    draft["estimated_reading_time"] = 4
    cfg = _config(tmp_path / "out", tmp_path / "images")
    fm = build_frontmatter(draft, [], cfg, publish_date="2026-05-07")
    assert fm["readingTime"] == 4


def test_frontmatter_computes_reading_time_when_missing(tmp_path: Path):
    draft = _good_draft()
    draft.pop("estimated_reading_time")
    cfg = _config(tmp_path / "out", tmp_path / "images")
    fm = build_frontmatter(draft, [], cfg, publish_date="2026-05-07")
    assert fm["readingTime"] >= 1


def test_frontmatter_includes_og_image_when_asset_provided(tmp_path: Path):
    draft = _good_draft()
    cfg = _config(tmp_path / "out", tmp_path / "images")
    assets = [
        {
            "filename": "fed-cut-smb-borrowers-og.png",
            "type": "og-image",
            "alt_text": "Headline over branded background",
            "path": "/nonexistent/og.png",
        }
    ]
    fm = build_frontmatter(draft, assets, cfg, publish_date="2026-05-07")
    assert fm["ogImage"].endswith("fed-cut-smb-borrowers-og.png")
    assert fm["ogImageAlt"] == "Headline over branded background"


def test_frontmatter_relatedlinks_renamed_for_nextjs(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    fm = build_frontmatter(_good_draft(), [], cfg, publish_date="2026-05-07")
    assert fm["relatedLinks"][0]["anchorText"] == "working capital lines"
    assert fm["relatedLinks"][0]["target"] == "/products/credit-line"


# --- render_mdx -----------------------------------------------------------


def test_render_mdx_produces_parseable_frontmatter(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    rendered = render_mdx(_good_draft(), [], cfg, publish_date="2026-05-07")
    post = frontmatter.loads(rendered)
    assert post.metadata["title"] == "What the Fed Cut Means for SMB Borrowers"
    assert post.metadata["slug"] == "fed-cut-smb-borrowers"
    assert post.metadata["jsonLd"]["@type"] == "Article"
    # Headline rendered as H1 in body.
    assert post.content.startswith("# What the Fed Cut Means for SMB Borrowers")


def test_render_mdx_appends_cta_when_missing(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    rendered = render_mdx(_good_draft(), [], cfg, publish_date="2026-05-07")
    assert "See your rate in 60 seconds" in rendered
    assert "https://acmefintech.com/apply" in rendered


def test_render_mdx_does_not_double_append_cta(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    draft = _good_draft()
    draft["article_body"] = (
        draft["article_body"]
        + "\n\n[See your rate in 60 seconds](https://acmefintech.com/apply)"
    )
    rendered = render_mdx(draft, [], cfg, publish_date="2026-05-07")
    # Exactly one CTA link, not two.
    assert rendered.count("acmefintech.com/apply") == 1


# --- validate_mdx ---------------------------------------------------------


def test_validate_mdx_clean_passes(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    rendered = render_mdx(_good_draft(), [], cfg, publish_date="2026-05-07")
    issues = validate_mdx(
        rendered,
        expected_slug="fed-cut-smb-borrowers",
        expected_headline=_good_draft()["headline"],
        available_image_paths=set(),
    )
    errors = [i for i in issues if i.level == "error"]
    assert errors == [], errors


def test_validate_mdx_flags_missing_image_in_body(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    draft = _good_draft()
    draft["article_body"] += "\n\n![chart](/images/blog/missing-chart.png)\n"
    rendered = render_mdx(draft, [], cfg, publish_date="2026-05-07")
    issues = validate_mdx(
        rendered,
        expected_slug=draft["slug"],
        expected_headline=draft["headline"],
        available_image_paths=set(),  # no assets copied
    )
    errors = [i for i in issues if i.level == "error" and i.field == "body.images"]
    assert errors


def test_validate_mdx_flags_slug_mismatch(tmp_path: Path):
    cfg = _config(tmp_path / "out", tmp_path / "images")
    rendered = render_mdx(_good_draft(), [], cfg, publish_date="2026-05-07")
    issues = validate_mdx(
        rendered,
        expected_slug="different-slug",
        expected_headline=_good_draft()["headline"],
        available_image_paths=set(),
    )
    assert any(i.level == "error" and i.field == "frontmatter.slug" for i in issues)


# --- render_article (end-to-end) -----------------------------------------


def test_render_article_writes_mdx_and_returns_summary(tmp_path: Path):
    out_dir = tmp_path / "content" / "blog"
    image_dir = tmp_path / "public" / "images" / "blog"
    cfg = _config(out_dir, image_dir)
    result = render_article(_good_draft(), [], cfg)
    assert result.ok is True
    mdx_path = Path(result.mdx_path)
    assert mdx_path.exists()
    assert mdx_path.name == "fed-cut-smb-borrowers.mdx"
    content = mdx_path.read_text(encoding="utf-8")
    post = frontmatter.loads(content)
    assert post.metadata["title"] == _good_draft()["headline"]


def test_render_article_copies_real_asset_to_image_dir(tmp_path: Path):
    out_dir = tmp_path / "content" / "blog"
    image_dir = tmp_path / "public" / "images" / "blog"
    cfg = _config(out_dir, image_dir)
    # Create a fake asset on disk.
    src_asset = tmp_path / "tmp-asset.png"
    src_asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    assets = [
        {
            "filename": "fed-cut-smb-borrowers-og.png",
            "type": "og-image",
            "alt_text": "OG image",
            "path": str(src_asset),
        }
    ]
    result = render_article(_good_draft(), assets, cfg)
    assert result.ok is True
    copied = image_dir / "fed-cut-smb-borrowers-og.png"
    assert copied.exists()
    assert copied.read_bytes() == src_asset.read_bytes()
    assert str(copied) in result.assets_copied


def test_render_article_skips_missing_asset_files_silently(tmp_path: Path):
    """If an asset's `path` doesn't exist on disk, we just don't copy it."""
    out_dir = tmp_path / "content" / "blog"
    image_dir = tmp_path / "public" / "images" / "blog"
    cfg = _config(out_dir, image_dir)
    assets = [
        {
            "filename": "ghost.png",
            "type": "chart",
            "alt_text": "x",
            "path": "/totally/nonexistent/path.png",
        }
    ]
    result = render_article(_good_draft(), assets, cfg)
    # Article still renders fine — body doesn't reference ghost.png.
    assert result.ok is True
    assert result.assets_copied == []


# --- CLI ------------------------------------------------------------------


def test_publisher_cli_renders_and_returns_zero(tmp_path: Path):
    from content_engine.publisher import main

    out_dir = tmp_path / "content" / "blog"
    image_dir = tmp_path / "public" / "images" / "blog"
    cfg = _config(out_dir, image_dir)

    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(_good_draft()))
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))

    rc = main(
        [
            "render",
            "--draft",
            str(draft_path),
            "--config",
            str(cfg_path),
            "--out",
            str(out_dir),
            "--date",
            "2026-05-07",
        ]
    )
    assert rc == 0
    assert (out_dir / "fed-cut-smb-borrowers.mdx").exists()
