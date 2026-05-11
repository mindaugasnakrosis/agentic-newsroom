"""Asset producer — deterministic image generation (OG image, charts).

The agent (`agents/asset-producer.md`) decides *what* to produce; this
module owns *how the pixels look*. We use matplotlib for both OG images
and charts to keep the dep tree minimal — see templates/nextjs-article/
og-image.html for the upgrade path to a Playwright-rendered OG image
when teams want richer typography.

CLI usage:
    python -m content_engine.assets og --headline "..." --slug "..." \\
        --config config.yaml --out output_dir/

    python -m content_engine.assets chart --slug "..." --index 1 \\
        --title "..." --kind bar --data '[["Q1", 11200], ["Q2", 13200]]' \\
        --config config.yaml --out output_dir/
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend; never opens a window.
import matplotlib.pyplot as plt
import yaml


# OG image standard size used by Facebook, LinkedIn, X. Twitter accepts
# the same. 1200x630 at 100dpi means figsize=(12, 6.3).
OG_FIGSIZE = (12.0, 6.3)
OG_DPI = 100

# Headline wrap width that keeps text within the 1200px frame at our
# default font size. Tuned empirically against matplotlib defaults.
OG_HEADLINE_WRAP = 28
OG_HEADLINE_FONTSIZE = 56


def _load_config(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _brand_colors(config: dict[str, Any]) -> tuple[str, str]:
    company = config.get("company") or {}
    colors = company.get("brand_colors") or {}
    primary = colors.get("primary") or "#1a365d"
    accent = colors.get("accent") or "#e53e3e"
    return primary, accent


def _company_name(config: dict[str, Any]) -> str:
    return (config.get("company") or {}).get("name") or ""


def og_filename(slug: str) -> str:
    return f"{slug}-og.png"


def chart_filename(slug: str, index: int) -> str:
    return f"{slug}-chart-{index}.png"


# --- OG image -------------------------------------------------------------


def render_og_image(
    headline: str,
    slug: str,
    config: dict[str, Any],
    out_dir: str | Path,
) -> Path:
    """Render the article's 1200x630 OG image and return the written path."""
    out_path = Path(out_dir) / og_filename(slug)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    primary, accent = _brand_colors(config)
    company_name = _company_name(config)

    fig, ax = plt.subplots(figsize=OG_FIGSIZE, dpi=OG_DPI)
    fig.patch.set_facecolor(primary)
    ax.set_facecolor(primary)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.3)
    ax.axis("off")

    wrapped = "\n".join(textwrap.wrap(headline, width=OG_HEADLINE_WRAP)) or headline
    ax.text(
        0.6,
        3.6,
        wrapped,
        fontsize=OG_HEADLINE_FONTSIZE,
        color="#ffffff",
        weight="bold",
        verticalalignment="center",
        horizontalalignment="left",
        wrap=True,
    )

    # Accent bar at the left edge — visual anchor.
    ax.add_patch(
        plt.Rectangle((0.0, 0.0), 0.18, 6.3, color=accent, transform=ax.transData)
    )

    # Company name in the bottom-right corner if configured.
    if company_name:
        ax.text(
            11.6,
            0.6,
            company_name,
            fontsize=22,
            color="#ffffff",
            alpha=0.85,
            horizontalalignment="right",
        )

    fig.savefig(
        out_path,
        dpi=OG_DPI,
        bbox_inches=None,
        pad_inches=0,
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return out_path


# --- Charts ---------------------------------------------------------------


def render_chart(
    data: list[tuple[str, float]],
    title: str,
    kind: str,
    slug: str,
    index: int,
    config: dict[str, Any],
    out_dir: str | Path,
) -> Path:
    """Render a small data chart and return the written path.

    `data` is a list of (label, value) pairs. `kind` is one of "bar",
    "line", "pie". Bar is the default for tabular comparisons; line is
    for time-series; pie is for share-of-total (and only with 2-5
    slices — anything more becomes unreadable).
    """
    if not data:
        raise ValueError("Cannot render a chart with empty data.")
    if kind not in ("bar", "line", "pie"):
        raise ValueError(f"Unsupported chart kind: {kind!r}")

    out_path = Path(out_dir) / chart_filename(slug, index)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    primary, accent = _brand_colors(config)
    labels = [str(d[0]) for d in data]
    values = [float(d[1]) for d in data]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)

    if kind == "bar":
        ax.bar(labels, values, color=primary, edgecolor=accent, linewidth=1.5)
        ax.set_ylabel("")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
    elif kind == "line":
        ax.plot(labels, values, color=primary, linewidth=2.5, marker="o", markerfacecolor=accent)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
    elif kind == "pie":
        if len(values) > 5:
            raise ValueError(
                f"Pie charts with >5 slices are unreadable; got {len(values)}. "
                "Use a bar chart instead."
            )
        # Simple two-tone palette derived from brand. Good enough; teams
        # that want richer palettes can swap this for seaborn.
        palette = [primary, accent] * ((len(values) + 1) // 2)
        ax.pie(values, labels=labels, colors=palette[: len(values)], autopct="%1.0f%%")
        ax.set_aspect("equal")

    ax.set_title(title, fontsize=14, weight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path


# --- CLI ------------------------------------------------------------------


def _emit(asset: dict[str, Any]) -> None:
    json.dump(asset, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _cmd_og(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    out_path = render_og_image(args.headline, args.slug, config, args.out)
    asset = {
        "filename": out_path.name,
        "type": "og-image",
        "alt_text": "",  # filled by the agent layer
        "path": str(out_path.resolve()),
    }
    _emit(asset)
    return 0


def _cmd_chart(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    try:
        raw = json.loads(args.data)
    except json.JSONDecodeError as ex:
        print(f"error: --data is not valid JSON: {ex}", file=sys.stderr)
        return 2
    if not isinstance(raw, list) or not all(
        isinstance(p, list) and len(p) == 2 for p in raw
    ):
        print("error: --data must be a JSON array of [label, value] pairs.", file=sys.stderr)
        return 2

    try:
        out_path = render_chart(
            data=[(p[0], p[1]) for p in raw],
            title=args.title,
            kind=args.kind,
            slug=args.slug,
            index=args.index,
            config=config,
            out_dir=args.out,
        )
    except ValueError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2

    asset = {
        "filename": out_path.name,
        "type": "chart",
        "alt_text": "",
        "path": str(out_path.resolve()),
    }
    _emit(asset)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="content_engine.assets")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_og = sub.add_parser("og", help="Render a 1200x630 OG image.")
    p_og.add_argument("--headline", required=True)
    p_og.add_argument("--slug", required=True)
    p_og.add_argument("--config", required=True)
    p_og.add_argument("--out", required=True)
    p_og.set_defaults(func=_cmd_og)

    p_chart = sub.add_parser("chart", help="Render a chart from inline data.")
    p_chart.add_argument("--slug", required=True)
    p_chart.add_argument("--index", type=int, required=True)
    p_chart.add_argument("--title", required=True)
    p_chart.add_argument("--kind", choices=["bar", "line", "pie"], default="bar")
    p_chart.add_argument(
        "--data", required=True, help='JSON array of [label, value] pairs.'
    )
    p_chart.add_argument("--config", required=True)
    p_chart.add_argument("--out", required=True)
    p_chart.set_defaults(func=_cmd_chart)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
