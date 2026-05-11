"""Tests for the asset producer module — OG image and chart rendering."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
import yaml

from content_engine.assets import (
    OG_DPI,
    OG_FIGSIZE,
    chart_filename,
    main,
    og_filename,
    render_chart,
    render_og_image,
)


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG width/height from the IHDR chunk without pulling in Pillow."""
    data = path.read_bytes()
    assert data.startswith(PNG_MAGIC), f"{path} is not a PNG."
    # IHDR chunk starts at byte 16; width is bytes 16-20, height 20-24.
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    return width, height


def _config() -> dict:
    return {
        "company": {
            "name": "Acme Fintech",
            "brand_colors": {"primary": "#1a365d", "accent": "#e53e3e"},
        }
    }


# --- Filename conventions -------------------------------------------------


def test_og_filename_format():
    assert og_filename("fed-cut-smb-borrowers") == "fed-cut-smb-borrowers-og.png"


def test_chart_filename_format():
    assert chart_filename("my-slug", 1) == "my-slug-chart-1.png"
    assert chart_filename("my-slug", 2) == "my-slug-chart-2.png"


# --- OG image -------------------------------------------------------------


def test_render_og_image_writes_file_at_correct_dimensions(tmp_path: Path):
    out = render_og_image(
        headline="What the Fed Cut Means for SMB Borrowers",
        slug="fed-cut",
        config=_config(),
        out_dir=tmp_path,
    )
    assert out.exists()
    assert out.name == "fed-cut-og.png"
    width, height = _png_dimensions(out)
    expected_w = int(OG_FIGSIZE[0] * OG_DPI)
    expected_h = int(OG_FIGSIZE[1] * OG_DPI)
    assert width == expected_w
    assert height == expected_h


def test_render_og_image_handles_long_headline(tmp_path: Path):
    long_headline = (
        "This Is An Unreasonably Long Headline That Will Definitely Need To Be "
        "Wrapped Across Several Lines To Fit Within The Output Frame"
    )
    out = render_og_image(long_headline, "long", _config(), tmp_path)
    assert out.exists()
    # Just confirm no crash + file written; visual quality is a human call.


def test_render_og_image_uses_default_colors_when_config_missing_brand(tmp_path: Path):
    cfg = {"company": {"name": "X"}}
    out = render_og_image("Hello", "hello", cfg, tmp_path)
    assert out.exists()


def test_render_og_image_works_with_no_company_name(tmp_path: Path):
    cfg = {"company": {"brand_colors": {"primary": "#000", "accent": "#fff"}}}
    out = render_og_image("Hello", "hello", cfg, tmp_path)
    assert out.exists()


# --- Charts ---------------------------------------------------------------


def test_render_bar_chart(tmp_path: Path):
    out = render_chart(
        data=[("Q1", 11200), ("Q2", 13200), ("Q3", 15400)],
        title="SBA loan approvals (2026)",
        kind="bar",
        slug="sba-q3",
        index=1,
        config=_config(),
        out_dir=tmp_path,
    )
    assert out.exists()
    assert out.name == "sba-q3-chart-1.png"
    width, height = _png_dimensions(out)
    # tight_layout may shave a few pixels; sanity bounds are enough.
    assert width >= 600 and height >= 300


def test_render_line_chart(tmp_path: Path):
    out = render_chart(
        data=[("Jan", 10), ("Feb", 12), ("Mar", 9), ("Apr", 14)],
        title="Trend",
        kind="line",
        slug="trend",
        index=1,
        config=_config(),
        out_dir=tmp_path,
    )
    assert out.exists()


def test_render_pie_chart_within_limits(tmp_path: Path):
    out = render_chart(
        data=[("A", 30), ("B", 50), ("C", 20)],
        title="Share",
        kind="pie",
        slug="share",
        index=1,
        config=_config(),
        out_dir=tmp_path,
    )
    assert out.exists()


def test_render_pie_chart_rejects_too_many_slices(tmp_path: Path):
    with pytest.raises(ValueError, match="unreadable"):
        render_chart(
            data=[("a", 1), ("b", 1), ("c", 1), ("d", 1), ("e", 1), ("f", 1)],
            title="Too many",
            kind="pie",
            slug="x",
            index=1,
            config=_config(),
            out_dir=tmp_path,
        )


def test_render_chart_rejects_empty_data(tmp_path: Path):
    with pytest.raises(ValueError, match="empty"):
        render_chart(
            data=[],
            title="Empty",
            kind="bar",
            slug="x",
            index=1,
            config=_config(),
            out_dir=tmp_path,
        )


def test_render_chart_rejects_unknown_kind(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported"):
        render_chart(
            data=[("a", 1)],
            title="x",
            kind="scatter",  # not supported
            slug="x",
            index=1,
            config=_config(),
            out_dir=tmp_path,
        )


# --- CLI ------------------------------------------------------------------


def test_og_cli_writes_file_and_emits_manifest_entry(tmp_path: Path, capsys):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(_config()))
    rc = main(
        [
            "og",
            "--headline",
            "Hello World",
            "--slug",
            "hello-world",
            "--config",
            str(cfg_path),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    manifest = json.loads(out)
    assert manifest["type"] == "og-image"
    assert manifest["filename"] == "hello-world-og.png"
    assert Path(manifest["path"]).exists()


def test_chart_cli_with_valid_data(tmp_path: Path, capsys):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(_config()))
    rc = main(
        [
            "chart",
            "--slug",
            "demo",
            "--index",
            "1",
            "--title",
            "Demo",
            "--kind",
            "bar",
            "--data",
            json.dumps([["Q1", 10], ["Q2", 20]]),
            "--config",
            str(cfg_path),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["type"] == "chart"
    assert manifest["filename"] == "demo-chart-1.png"
    assert Path(manifest["path"]).exists()


def test_chart_cli_rejects_bad_json_data(tmp_path: Path, capsys):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(_config()))
    rc = main(
        [
            "chart",
            "--slug",
            "demo",
            "--index",
            "1",
            "--title",
            "Demo",
            "--kind",
            "bar",
            "--data",
            "not-json{",
            "--config",
            str(cfg_path),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "valid JSON" in err


def test_chart_cli_rejects_wrong_data_shape(tmp_path: Path, capsys):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(_config()))
    rc = main(
        [
            "chart",
            "--slug",
            "demo",
            "--index",
            "1",
            "--title",
            "Demo",
            "--kind",
            "bar",
            "--data",
            json.dumps({"not": "a list"}),
            "--config",
            str(cfg_path),
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == 2
