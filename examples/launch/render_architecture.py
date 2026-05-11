"""Render the content-engine architecture diagram for the Medium post.

Produces examples/launch/architecture.png at 1600x800 (Medium-friendly,
looks good at retina scale). Edit the constants below to retitle.

Run:
    python examples/launch/render_architecture.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt

# --- Style ---------------------------------------------------------------

FIG_SIZE = (16.0, 8.0)
DPI = 100  # 16*100 x 8*100 = 1600x800

BG = "#fafafa"
TITLE_COLOR = "#0f172a"
AGENT_FILL = "#0f172a"  # near-black
AGENT_TEXT = "#ffffff"
ROLE_TEXT = "#cbd5e1"
ARROW_COLOR = "#0f172a"
HUMAN_FILL = "#f97316"  # orange
HUMAN_TEXT = "#ffffff"
NOTE_COLOR = "#64748b"
ACCENT = "#0ea5e9"  # cyan for the CLI underline

# --- Layout --------------------------------------------------------------

AGENT_BOXES = [
    {"name": "news-scanner",      "role": "ranks RSS + web search"},
    {"name": "content-strategist", "role": "writes original analysis"},
    {"name": "asset-producer",     "role": "OG image + charts"},
    {"name": "publisher",          "role": "MDX + JSON-LD + git PR"},
]

HUMAN_GATES = [
    {"after_index": 0, "label": "HUMAN PICKS"},
    {"after_index": 1, "label": "HUMAN REVIEWS"},
]


def _rounded_box(ax, x, y, w, h, fill, edge=None, lw=0):
    box = patches.FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.15",
        linewidth=lw,
        facecolor=fill,
        edgecolor=edge or fill,
    )
    ax.add_patch(box)


def _arrow(ax, x1, y1, x2, y2, color=ARROW_COLOR, lw=3.0):
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(
            arrowstyle="-|>,head_length=0.45,head_width=0.28",
            color=color,
            lw=lw,
            shrinkA=0,
            shrinkB=0,
        ),
    )


def render(out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 8)
    ax.axis("off")

    # Title
    ax.text(
        0.6,
        7.2,
        "content-engine",
        fontsize=34,
        color=TITLE_COLOR,
        weight="bold",
    )
    ax.text(
        0.6,
        6.65,
        "a four-agent AI pipeline that turns industry news into publish-ready articles",
        fontsize=15,
        color=NOTE_COLOR,
    )

    # Agent boxes
    n = len(AGENT_BOXES)
    gap = 0.6
    margin_x = 0.6
    available = 16 - 2 * margin_x - (n - 1) * gap
    box_w = available / n
    box_h = 2.0
    y_box = 3.5

    centers_x = []
    for i, agent in enumerate(AGENT_BOXES):
        x = margin_x + i * (box_w + gap)
        _rounded_box(ax, x, y_box, box_w, box_h, AGENT_FILL)
        cx = x + box_w / 2
        centers_x.append(cx)

        # Agent name
        ax.text(
            cx,
            y_box + box_h * 0.62,
            agent["name"],
            fontsize=18,
            color=AGENT_TEXT,
            weight="bold",
            ha="center",
        )
        # Agent role
        ax.text(
            cx,
            y_box + box_h * 0.30,
            agent["role"],
            fontsize=13,
            color=ROLE_TEXT,
            ha="center",
        )

    # Arrows between agent boxes
    arrow_y = y_box + box_h / 2
    for i in range(n - 1):
        x_from = margin_x + (i + 1) * box_w + i * gap
        x_to = x_from + gap
        _arrow(ax, x_from + 0.05, arrow_y, x_to - 0.05, arrow_y)

    # Human gates as orange pills below, with up-arrows into the relevant agent
    pill_h = 0.6
    pill_w = 2.4
    pill_y = 1.55
    for gate in HUMAN_GATES:
        # The gate sits between agents at index `after_index` and `after_index+1`
        # Center it on the arrow between those two boxes.
        x_arrow = margin_x + (gate["after_index"] + 1) * box_w + gate["after_index"] * gap + gap / 2
        pill_x = x_arrow - pill_w / 2
        _rounded_box(ax, pill_x, pill_y, pill_w, pill_h, HUMAN_FILL)
        ax.text(
            x_arrow,
            pill_y + pill_h / 2,
            gate["label"],
            fontsize=12,
            color=HUMAN_TEXT,
            weight="bold",
            ha="center",
            va="center",
        )
        # Up-arrow from pill toward the connecting arrow between agents
        _arrow(ax, x_arrow, pill_y + pill_h + 0.05, x_arrow, arrow_y - 0.05, color=HUMAN_FILL, lw=2.5)

    # CLI underline / annotation
    cli_y = 0.7
    ax.plot([0.6, 15.4], [cli_y + 0.35, cli_y + 0.35], color=ACCENT, lw=2.5)
    ax.text(
        0.6,
        cli_y,
        "Python CLI",
        fontsize=14,
        color=TITLE_COLOR,
        weight="bold",
    )
    ax.text(
        2.4,
        cli_y,
        "— deterministic boundary work: RSS scoring, source prefetch, MDX render, image gen, schema.org JSON-LD, validation",
        fontsize=12,
        color=NOTE_COLOR,
        va="baseline",
    )

    fig.savefig(out_path, dpi=DPI, facecolor=BG, bbox_inches=None, pad_inches=0.1)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    out = Path(__file__).parent / "architecture.png"
    path = render(out)
    print(f"Wrote: {path.resolve()}  ({path.stat().st_size // 1024} KB)")
