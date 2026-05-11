"""Render a Medium-screenshot-worthy preview of a content-engine article.

Produces two files in examples/launch/:

    article-hero.png     — stylized "Fed funds rate" hero chart (matplotlib)
    article-preview.html — full editorial-style article page

Open `article-preview.html` in your browser (we'll do that for you at the
end) and screenshot the result for the Medium post.

The HTML uses the bundled sample-draft.json as the article content so the
preview reflects exactly what the publisher emits. Edit the SAMPLE_DRAFT
path if you want to preview a different article.
"""

from __future__ import annotations

import json
import webbrowser
from html import escape
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
SAMPLE_DRAFT = REPO_ROOT / "examples" / "sample-draft.json"
HERO_PATH = HERE / "article-hero.png"
HTML_PATH = HERE / "article-preview.html"


# --- Hero image: editorial-style "Fed funds rate" chart -----------------


def render_hero(out_path: Path) -> Path:
    """Stylized Fed funds rate chart, 2020-2026. Editorial / data-journalism look."""
    fig, ax = plt.subplots(figsize=(13.0, 6.5), dpi=120)

    # Approximate Fed funds rate path, 2020-2026 (illustrative).
    months = np.arange(0, 78)
    rates = np.array(
        [
            # 2020 (COVID floor)
            0.25, 0.25, 0.25, 0.25, 0.25, 0.25,
            0.25, 0.25, 0.25, 0.25, 0.25, 0.25,
            # 2021
            0.25, 0.25, 0.25, 0.25, 0.25, 0.25,
            0.25, 0.25, 0.25, 0.25, 0.25, 0.25,
            # 2022 — rapid hikes
            0.50, 0.75, 1.00, 1.50, 2.00, 2.50,
            3.00, 3.25, 3.75, 4.25, 4.50, 4.75,
            # 2023 — peak
            4.75, 5.00, 5.00, 5.25, 5.25, 5.25,
            5.25, 5.50, 5.50, 5.50, 5.50, 5.50,
            # 2024 — plateau then first cuts
            5.50, 5.50, 5.50, 5.50, 5.25, 5.00,
            5.00, 4.75, 4.75, 4.50, 4.50, 4.25,
            # 2025 — gradual cuts
            4.25, 4.00, 4.00, 3.75, 3.75, 3.50,
            3.50, 3.50, 3.25, 3.25, 3.00, 3.00,
            # 2026 (through May) — small cut this week
            3.00, 3.00, 3.00, 3.00, 2.75, 2.75,
        ]
    )

    ax.plot(months, rates, color="#0f172a", linewidth=2.5, solid_capstyle="round")
    ax.fill_between(months, 0, rates, color="#0f172a", alpha=0.05)

    # Highlight the latest cut.
    cut_idx = 76
    ax.scatter([months[cut_idx]], [rates[cut_idx]], color="#dc2626", s=110, zorder=5)
    ax.annotate(
        "25bp cut\nMay 6, 2026",
        xy=(months[cut_idx], rates[cut_idx]),
        xytext=(months[cut_idx] - 14, rates[cut_idx] + 1.2),
        fontsize=12,
        color="#dc2626",
        weight="bold",
        ha="center",
        arrowprops=dict(arrowstyle="-", color="#dc2626", lw=1.2),
    )

    ax.set_ylim(0, 6.2)
    ax.set_xlim(0, 78)
    # X ticks at year boundaries
    year_starts = [0, 12, 24, 36, 48, 60, 72]
    year_labels = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
    ax.set_xticks(year_starts)
    ax.set_xticklabels(year_labels, fontsize=11, color="#475569")
    ax.set_yticks([0, 1, 2, 3, 4, 5])
    ax.set_yticklabels(["0%", "1%", "2%", "3%", "4%", "5%"], fontsize=11, color="#475569")

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#cbd5e1")
    ax.spines["bottom"].set_color("#cbd5e1")
    ax.tick_params(colors="#cbd5e1")
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.8)
    ax.set_axisbelow(True)

    # Chart label (top-left)
    ax.text(
        0.0,
        6.0,
        "FEDERAL FUNDS RATE  •  TARGET UPPER BOUND",
        fontsize=10,
        color="#64748b",
        weight="bold",
        transform=ax.transData,
    )

    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")
    fig.tight_layout(pad=1.2)
    fig.savefig(out_path, dpi=120, facecolor="#ffffff", bbox_inches="tight")
    plt.close(fig)
    return out_path


# --- HTML article preview -------------------------------------------------


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title} — Acme Fintech</title>
<style>
  :root {{
    --ink: #0f172a;
    --muted: #475569;
    --rule: #e2e8f0;
    --kicker: #dc2626;
    --bg: #ffffff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    background: var(--bg);
    color: var(--ink);
    font-family: "Charter", "Iowan Old Style", "Georgia", "Times New Roman", serif;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }}
  .masthead {{
    border-bottom: 1px solid var(--rule);
    padding: 18px 32px;
    text-align: center;
    font-family: "Helvetica Neue", "Inter", system-ui, sans-serif;
    letter-spacing: 0.22em;
    font-size: 13px;
    font-weight: 700;
    color: var(--ink);
    text-transform: uppercase;
  }}
  .masthead small {{
    display: block;
    margin-top: 4px;
    font-family: "Charter", "Georgia", serif;
    letter-spacing: 0;
    font-size: 11px;
    font-weight: 400;
    color: var(--muted);
    text-transform: none;
    font-style: italic;
  }}
  article {{
    max-width: 720px;
    margin: 56px auto 80px;
    padding: 0 24px;
  }}
  .kicker {{
    font-family: "Helvetica Neue", "Inter", system-ui, sans-serif;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--kicker);
    margin-bottom: 18px;
  }}
  h1 {{
    font-family: "Charter", "Iowan Old Style", "Georgia", serif;
    font-size: 44px;
    line-height: 1.12;
    font-weight: 700;
    letter-spacing: -0.01em;
    margin-bottom: 18px;
  }}
  .subdeck {{
    font-size: 21px;
    line-height: 1.42;
    color: var(--muted);
    font-style: italic;
    margin-bottom: 28px;
  }}
  .byline {{
    font-family: "Helvetica Neue", "Inter", system-ui, sans-serif;
    font-size: 13px;
    color: var(--muted);
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
    padding: 14px 0;
    margin-bottom: 32px;
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
  }}
  .byline .author {{
    color: var(--ink);
    font-weight: 600;
  }}
  figure.hero {{
    margin: 0 0 32px;
  }}
  figure.hero img {{
    width: 100%;
    display: block;
    border-radius: 2px;
  }}
  figcaption {{
    font-family: "Helvetica Neue", "Inter", system-ui, sans-serif;
    font-size: 13px;
    color: var(--muted);
    margin-top: 10px;
    line-height: 1.45;
  }}
  figcaption strong {{
    color: var(--ink);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-size: 11px;
    margin-right: 6px;
  }}
  .body p {{
    font-size: 19px;
    line-height: 1.65;
    margin-bottom: 22px;
    color: var(--ink);
  }}
  .body p.lead::first-letter {{
    font-size: 72px;
    line-height: 0.85;
    float: left;
    padding: 4px 10px 0 0;
    font-weight: 700;
    color: var(--ink);
  }}
  .body h2 {{
    font-family: "Charter", "Georgia", serif;
    font-size: 26px;
    line-height: 1.25;
    font-weight: 700;
    margin: 38px 0 14px;
  }}
  .pullquote {{
    border-left: 4px solid var(--kicker);
    padding: 6px 0 6px 22px;
    margin: 36px 0;
    font-size: 24px;
    line-height: 1.35;
    color: var(--ink);
    font-style: italic;
  }}
  .source {{
    font-family: "Helvetica Neue", "Inter", system-ui, sans-serif;
    font-size: 13px;
    color: var(--muted);
    border-top: 1px solid var(--rule);
    margin-top: 40px;
    padding-top: 20px;
  }}
  .source a {{
    color: var(--ink);
    text-decoration: none;
    border-bottom: 1px solid var(--rule);
  }}
</style>
</head>
<body>

<div class="masthead">
  Acme Fintech
  <small>What small business owners need to know — written daily.</small>
</div>

<article>
  <div class="kicker">Economics · {reading_time} min read</div>
  <h1>{headline}</h1>
  <p class="subdeck">{subdeck}</p>

  <div class="byline">
    <span><span class="author">By Acme Fintech Editorial</span> · {pretty_date}</span>
    <span>Updated {pretty_date}</span>
  </div>

  <figure class="hero">
    <img src="article-hero.png" alt="Federal funds rate chart, 2020 to May 2026, showing the 25bp cut on May 6, 2026." />
    <figcaption>
      <strong>Chart</strong>
      The Fed's benchmark rate over six years. Tuesday's 25bp cut is the smallest move
      since the 2024 pivot — and the first since November. <span style="color: var(--muted)">Source: Federal Reserve.</span>
    </figcaption>
  </figure>

  <div class="body">
    <p class="lead">{lead_paragraph}</p>
    <p>{second_paragraph}</p>

    <h2>{section_one_heading}</h2>
    <p>{section_one_body}</p>

    <blockquote class="pullquote">
      “Fixed-rate SBA 7(a) loans originated this year won't reprice at all. If you locked in at
      11.5%, you stay at 11.5% for the life of the loan.”
    </blockquote>

    <p>{section_one_para_two}</p>

    <h2>{section_two_heading}</h2>
    <p>{section_two_body}</p>
  </div>

  <div class="source">
    Originally reported by <a href="{source_url}">{source_publisher} — {source_title}</a>.
    Analysis by Acme Fintech Editorial.
  </div>
</article>

</body>
</html>
"""


def _split_body(body: str) -> dict[str, str]:
    """Carve the sample draft's body into the chunks the HTML template wants."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    # Expected shape: lead, second, ## section1, p, p, ## section2, p
    chunks: dict[str, str] = {
        "lead_paragraph": paragraphs[0],
        "second_paragraph": paragraphs[1],
    }
    # Walk the rest and pair section headings with the paragraph after.
    sections: list[tuple[str, list[str]]] = []
    cur_heading: str | None = None
    cur_body: list[str] = []
    for p in paragraphs[2:]:
        if p.startswith("## "):
            if cur_heading is not None:
                sections.append((cur_heading, cur_body))
            cur_heading = p[3:].strip()
            cur_body = []
        else:
            cur_body.append(p)
    if cur_heading is not None:
        sections.append((cur_heading, cur_body))

    # Take the first two sections.
    if len(sections) >= 1:
        h1, b1 = sections[0]
        chunks["section_one_heading"] = h1
        chunks["section_one_body"] = b1[0] if b1 else ""
        chunks["section_one_para_two"] = b1[1] if len(b1) > 1 else ""
    if len(sections) >= 2:
        h2, b2 = sections[1]
        chunks["section_two_heading"] = h2
        chunks["section_two_body"] = b2[0] if b2 else ""
    return chunks


def render_html(out_path: Path) -> Path:
    draft = json.loads(SAMPLE_DRAFT.read_text(encoding="utf-8"))
    body_chunks = _split_body(draft["article_body"])

    fields = {
        "title": escape(draft["headline"]),
        "headline": escape(draft["headline"]),
        "subdeck": escape(draft["meta_description"]),
        "reading_time": draft.get("estimated_reading_time", 3),
        "pretty_date": "May 8, 2026",
        "lead_paragraph": escape(body_chunks.get("lead_paragraph", "")),
        "second_paragraph": escape(body_chunks.get("second_paragraph", "")),
        "section_one_heading": escape(body_chunks.get("section_one_heading", "")),
        "section_one_body": escape(body_chunks.get("section_one_body", "")),
        "section_one_para_two": escape(body_chunks.get("section_one_para_two", "")),
        "section_two_heading": escape(body_chunks.get("section_two_heading", "")),
        "section_two_body": escape(body_chunks.get("section_two_body", "")),
        "source_url": escape(draft["source_attribution"]["url"]),
        "source_title": escape(draft["source_attribution"]["title"]),
        "source_publisher": escape(draft["source_attribution"]["publisher"]),
    }
    html = HTML_TEMPLATE.format(**fields)
    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    hero = render_hero(HERO_PATH)
    html = render_html(HTML_PATH)
    print(f"Wrote: {hero.resolve()}  ({hero.stat().st_size // 1024} KB)")
    print(f"Wrote: {html.resolve()}  ({html.stat().st_size // 1024} KB)")
    print()
    print("Opening in your default browser. Use Cmd+Shift+4 (macOS) to screenshot.")
    webbrowser.open(html.as_uri())
