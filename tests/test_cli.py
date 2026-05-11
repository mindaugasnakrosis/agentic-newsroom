"""Tests for the top-level `content-engine` CLI.

We use click's CliRunner to drive the CLI in-process, isolated from the
real filesystem when needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from content_engine.cli import cli


FIXTURES = Path(__file__).parent / "fixtures"


def _config_with_local_feed(tmp_path: Path, feed_path: Path) -> Path:
    """Write a config that points scanner at a local RSS file via file:// URL."""
    base = yaml.safe_load((FIXTURES / "sample-config.yaml").read_text())
    base["content"]["sources"]["rss_feeds"] = [feed_path.as_uri()]
    out = tmp_path / "cfg.yaml"
    out.write_text(yaml.safe_dump(base))
    return out


def _good_draft() -> dict:
    body = (
        "Intro paragraph that mentions interest rates and small business loans.\n\n"
        "## What changed\n\nProse with SBA loans and working capital.\n\n"
        "## What this means\n\nClosing analysis with interest rates context.\n"
    )
    return {
        "headline": "What the Fed Cut Means for SMB Borrowers",
        "meta_description": (
            "The Fed's 25bp cut won't change small business loans overnight — "
            "here's the realistic timeline."
        ),
        "slug": "fed-cut-smb-borrowers",
        "target_keywords": ["interest rates", "small business loans", "SBA loans"],
        "article_body": body,
        "schema_type": "Article",
        "estimated_reading_time": 1,
    }


# --- Top-level -------------------------------------------------------------


def test_cli_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cmd in ("scan", "draft", "assets", "publish", "run"):
        assert cmd in result.output


# --- scan ------------------------------------------------------------------


def test_scan_emits_json_for_local_feed(tmp_path):
    cfg_path = _config_with_local_feed(tmp_path, FIXTURES / "sample-rss.xml")
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--config", str(cfg_path), "--output", "json"])
    assert result.exit_code == 0, result.output
    items = json.loads(result.output)
    assert isinstance(items, list)
    # Sample feed contains one item dated Jan 2025 (out of date_range) plus
    # several within range — at least one should survive the filter.
    assert len(items) >= 1
    for item in items:
        assert "title" in item and "url" in item and "relevance_score" in item


def test_scan_table_output_format(tmp_path):
    cfg_path = _config_with_local_feed(tmp_path, FIXTURES / "sample-rss.xml")
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--config", str(cfg_path), "--output", "table"])
    assert result.exit_code == 0, result.output
    # Table format includes a leading "[score]" bracketed prefix.
    assert "[" in result.output and "]" in result.output


# --- draft -----------------------------------------------------------------


def test_draft_slug_subcommand():
    runner = CliRunner()
    result = runner.invoke(cli, ["draft", "slug", "Hello, World! Some Headline"])
    assert result.exit_code == 0
    assert result.output.strip() == "hello-world-some-headline"


def test_draft_validate_passes_clean_draft(tmp_path):
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(_good_draft()))
    runner = CliRunner()
    result = runner.invoke(cli, ["draft", "validate", "--draft", str(draft_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True


def test_draft_validate_rejects_bad_draft(tmp_path):
    bad = _good_draft()
    bad["headline"] = "X" * 200  # exceeds HEADLINE_MAX
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(bad))
    runner = CliRunner()
    result = runner.invoke(cli, ["draft", "validate", "--draft", str(draft_path)])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert any(i["field"] == "headline" for i in payload["issues"])


# --- assets ----------------------------------------------------------------


def test_assets_og_subcommand_writes_file(tmp_path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text((FIXTURES / "sample-config.yaml").read_text())
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "assets",
            "og",
            "--headline",
            "Hello World",
            "--slug",
            "hello-world",
            "--config",
            str(cfg_path),
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads(result.output)
    assert manifest["filename"] == "hello-world-og.png"
    assert Path(manifest["path"]).exists()


def test_assets_chart_rejects_bad_json(tmp_path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text((FIXTURES / "sample-config.yaml").read_text())
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "assets",
            "chart",
            "--slug",
            "x",
            "--index",
            "1",
            "--title",
            "T",
            "--kind",
            "bar",
            "--data",
            "not-json{",
            "--config",
            str(cfg_path),
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0


# --- publish ---------------------------------------------------------------


def test_publish_renders_mdx(tmp_path):
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(_good_draft()))
    cfg = yaml.safe_load((FIXTURES / "sample-config.yaml").read_text())
    cfg["publishing"]["output_dir"] = str(tmp_path / "blog")
    cfg["publishing"]["nextjs"]["image_dir"] = str(tmp_path / "public" / "images" / "blog")
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "publish",
            "--draft",
            str(draft_path),
            "--config",
            str(cfg_path),
            "--date",
            "2026-05-08",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert Path(payload["mdx_path"]).exists()


# --- run -------------------------------------------------------------------


def test_run_aborts_when_no_candidates(tmp_path):
    """If feeds yield nothing above min_relevance_score, run should error cleanly."""
    cfg = yaml.safe_load((FIXTURES / "sample-config.yaml").read_text())
    cfg["content"]["sources"]["rss_feeds"] = []  # no feeds
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--config", str(cfg_path)])
    assert result.exit_code != 0
    assert "No candidates" in result.output or "No candidates" in (result.stderr or "")


def test_run_resume_advances_through_stages(tmp_path):
    """Pre-seed every working-dir file and confirm `run --resume` walks to the publish step."""
    cfg = yaml.safe_load((FIXTURES / "sample-config.yaml").read_text())
    cfg["publishing"]["output_dir"] = str(tmp_path / "blog")
    cfg["publishing"]["nextjs"]["image_dir"] = str(tmp_path / "public" / "images" / "blog")
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))

    workdir = tmp_path / "run"
    workdir.mkdir()

    # Stage 1: selection
    (workdir / "selected.json").write_text(
        json.dumps(
            {
                "title": "Fake News",
                "source": "test",
                "url": "https://example.test/article",
                "published_date": "2026-05-01",
                "summary": "",
                "relevance_score": 80,
                "seo_potential": "high",
                "suggested_angle": "",
                "matched_keywords": [],
            }
        )
    )
    # Stage 2: brief (skip the network prefetch by pre-seeding)
    (workdir / "brief.json").write_text(json.dumps({"status": "ok", "url": "x", "text": "y"}))
    # Stage 3: validated draft
    (workdir / "draft.json").write_text(json.dumps(_good_draft()))
    # Stage 4: empty assets manifest is acceptable (no files to copy)
    (workdir / "assets.json").write_text("[]")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--config",
            str(cfg_path),
            "--workdir",
            str(workdir),
            "--resume",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Article rendered" in result.output


def test_run_pauses_at_draft_handoff(tmp_path):
    """When a selection exists but no draft, run prints next-step instructions and exits 0."""
    cfg = yaml.safe_load((FIXTURES / "sample-config.yaml").read_text())
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))

    workdir = tmp_path / "run"
    workdir.mkdir()
    (workdir / "selected.json").write_text(
        json.dumps(
            {
                "title": "Fake",
                "source": "test",
                "url": "https://example.test/article",
                "published_date": "2026-05-01",
                "summary": "",
                "relevance_score": 80,
                "seo_potential": "high",
                "suggested_angle": "",
                "matched_keywords": [],
            }
        )
    )
    (workdir / "brief.json").write_text(json.dumps({"status": "ok", "url": "x", "text": "y"}))

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["run", "--config", str(cfg_path), "--workdir", str(workdir), "--resume"],
    )
    assert result.exit_code == 0, result.output
    assert "content-strategist" in result.output
