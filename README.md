# agentic-newsroom 📰

> **AI agents that read industry news and write the articles for you.** A four-agent Claude Code pipeline that scans RSS feeds every morning, picks the stories worth writing about, and drafts publish-ready Next.js MDX articles — with SEO metadata, social images, and a pull request. A human reviews the draft before anything ships.

![license](https://img.shields.io/badge/license-MIT-orange) ![python](https://img.shields.io/badge/python-3.10+-blue) ![tests](https://img.shields.io/badge/tests-93%20passing-brightgreen) ![built with](https://img.shields.io/badge/built%20with-Claude%20Code-d97757) ![status](https://img.shields.io/badge/status-active-success)

![Four-agent pipeline diagram: news-scanner ranks RSS feeds, content-strategist writes original analysis, asset-producer generates the OG image and charts, publisher renders MDX with JSON-LD and opens a git PR. Human review gates between scanner-strategist and strategist-publisher. A Python CLI underneath handles all deterministic boundary work.](examples/launch/architecture.png)

The package and CLI are named `content-engine`; the repository is `agentic-newsroom` to reflect the multi-agent newsroom architecture.

The agents do the judgment (which news matters, what angle to take, what
to write, when to draw a chart). The CLI does the boundary work (fetch
feeds, score them, prefetch source articles, render images, build
frontmatter, validate the MDX, copy assets). A human reviews the draft
between writing and publishing.

## What it does

```
                ┌─────────────────┐
                │  news-scanner   │  scores RSS + web search
                └────────┬────────┘
                         │ ranked candidates
                ┌────────▼────────┐
                │   HUMAN PICKS   │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │ content-strategist │  writes original analysis
                └────────┬────────┘
                         │ draft.json
                ┌────────▼────────┐
                │  HUMAN REVIEWS  │  ← gate
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │  asset-producer │  OG image + optional charts
                └────────┬────────┘
                         │ assets.json
                ┌────────▼────────┐
                │    publisher    │  MDX + JSON-LD, branch + PR
                └─────────────────┘
```

Each box is a Claude Code subagent (`agents/*.md`). The arrows are JSON
files written into a per-article working directory. The CLI
(`content-engine`) is the spine each agent calls for deterministic work.

## Install

Requires Python 3.10+. From the repo root:

```bash
pip install -e .
```

That installs the `content-engine` console script. Verify it landed:

```bash
content-engine --help
```

You should see five subcommands: `scan`, `draft`, `assets`, `publish`,
`run`.

The plugin manifest (`.claude-plugin/plugin.json`) registers four subagents
and the `content-engine` skill with Claude Code — see
[Use with Claude Code](#use-with-claude-code) below for that path.

## Try it end-to-end (no Claude Code required)

Every CLI stage is independently testable. This walkthrough exercises
each one against bundled fixtures so the result is deterministic — no
live RSS feeds, no LLM, no network. Run from the repo root.

### 1. Generate a slug

```bash
content-engine draft slug "What the Fed Cut Means for SMB Borrowers"
# → fed-cut-means-for-smb-borrowers
```

### 2. Scan the bundled fixture feed

The repo ships a small RSS fixture at `tests/fixtures/sample-rss.xml`
with four items dated May 2026. To point the scanner at it, write a tiny
config (or copy this one):

```bash
cat > smoke.yaml <<EOF
company:
  name: "Smoke Test Co"
  cta_url: "https://smoke.example.com/go"
  cta_text: "Try it"
  brand_colors: { primary: "#1a365d", accent: "#e53e3e" }
content:
  industry: "fintech"
  keywords: ["interest rates", "SBA loans", "small business"]
  sources:
    rss_feeds:
      - "file://$(pwd)/tests/fixtures/sample-rss.xml"
  date_range_days: 30
  min_relevance_score: 0
  max_articles_per_run: 5
publishing:
  output_dir: "./smoke-out/blog"
  nextjs: { image_dir: "./smoke-out/images" }
EOF

content-engine scan --config smoke.yaml --output table
```

Expected: three candidates with scores in the 25–50 range. The fourth
(Jan 2025) is filtered out by `date_range_days`.

### 3. Validate the sample draft

A pre-written draft lives at `examples/sample-draft.json`:

```bash
content-engine draft validate --draft examples/sample-draft.json
# → { "ok": true, "issues": [] }
```

### 4. Render an OG image and a chart

```bash
content-engine assets og \
  --headline "What the Fed Cut Means for SMB Borrowers" \
  --slug fed-cut-smb-borrowers \
  --config config/examples/fintech.yaml \
  --out ./smoke-out/assets

content-engine assets chart \
  --slug fed-cut-smb-borrowers --index 1 \
  --title "SBA loan approvals (2026)" --kind bar \
  --data '[["Q1", 11200], ["Q2", 13200], ["Q3", 15400]]' \
  --config config/examples/fintech.yaml \
  --out ./smoke-out/assets
```

Open `./smoke-out/assets/fed-cut-smb-borrowers-og.png` and
`fed-cut-smb-borrowers-chart-1.png` to inspect them.

### 5. Publish the sample draft to MDX

```bash
content-engine publish \
  --draft examples/sample-draft.json \
  --config config/examples/fintech.yaml \
  --out ./smoke-out/blog \
  --date 2026-05-08
```

Result: `./smoke-out/blog/fed-cut-smb-borrowers.mdx` with full
frontmatter, JSON-LD, and a CTA block. `cat` it to inspect.

### 6. Try a live scan against real feeds (optional)

```bash
content-engine scan --config config/examples/fintech.yaml --output table
```

This hits Bloomberg, Yahoo, and the Federal Reserve press feed in real
time. Yields vary day-to-day — if you get "(no candidates above
min_relevance_score)" that day's headlines simply didn't hit the
keywords; lower `min_relevance_score` in `fintech.yaml` to 0 to see
everything fetched.

### 7. Preview the article in a browser (optional)

`content-engine` produces MDX, not HTML — Next.js (or Astro/Gatsby/etc.)
is what turns it into a rendered page. If you don't have a Next.js
project set up yet and just want to eyeball the output, this snippet
strips the frontmatter, renders the body to plain HTML, and opens it:

```bash
pip install markdown
python <<'PY'
import frontmatter, markdown, pathlib, webbrowser
p = pathlib.Path("smoke-out/blog/fed-cut-smb-borrowers.mdx")
post = frontmatter.load(p)
body = markdown.markdown(post.content, extensions=["fenced_code", "tables"])
out = p.with_suffix(".html")
out.write_text(
    f"<!doctype html><meta charset=utf-8><title>{post['title']}</title>"
    "<style>body{font:16px/1.5 system-ui;max-width:680px;margin:2em auto;"
    "padding:0 1em}img{max-width:100%}h1,h2{line-height:1.2}</style>"
    f"<body>{body}"
)
webbrowser.open(out.absolute().as_uri())
PY
```

This is for inspection only — it doesn't render the JSON-LD, the OG
image, or any JSX components. Use a real Next.js setup for production
preview.

### 8. Clean up

```bash
rm -rf ./smoke-out smoke.yaml
```

## Quick start

```bash
# 1. Copy an example config and customize it.
cp config/examples/fintech.yaml my-config.yaml
$EDITOR my-config.yaml

# 2. Run the pipeline.
content-engine run --config my-config.yaml
```

That's the happy path. The `run` command walks you through every stage,
pausing at each agent handoff with explicit next-step instructions:

```
[1/4] Scanning RSS feeds defined in my-config.yaml ...
Top candidates:
   1. [ 78] Fed cuts interest rates by 25bp, signals further easing
        Federal Reserve  2026-05-06
        https://www.federalreserve.gov/...
   2. [ 64] SBA loan approvals climb 18% in Q1 amid easier credit
        Bloomberg  2026-05-04
        https://www.bloomberg.com/...
   ...

Which candidate? (1-N, or 0 to abort)
```

Pick one. The CLI prefetches the source article, then prints:

```
Next step — invoke the content-strategist agent in Claude Code.
  Tell the agent:
    - Source brief is at: runs/20260508-141522/brief.json
    - Config is at:       my-config.yaml
    - Save the draft JSON to: runs/20260508-141522/draft.json

When the draft file exists, re-run:
    content-engine run --config my-config.yaml --workdir runs/20260508-141522 --resume
```

In Claude Code, `@content-strategist` and follow the instruction. The agent
writes the draft. You re-run with `--resume`, the CLI validates the draft,
prints any warnings, and prompts you to invoke the asset-producer next.
After assets, the CLI renders the MDX. Then invoke the publisher agent for
the git commit + PR.

## Use with Claude Code

The four agents and the orchestrator skill are exposed via
`.claude-plugin/plugin.json`. To use them inside Claude Code:

1. Install the CLI (see above).
2. Tell Claude Code about this plugin directory. The simplest path is to
   open Claude Code in the repo root — it will detect the
   `.claude-plugin/plugin.json` manifest automatically and load:
   - `skills/content-engine/SKILL.md` as the orchestrator skill
   - `agents/news-scanner.md`, `content-strategist.md`,
     `asset-producer.md`, `publisher.md` as four subagents you can
     invoke with `@news-scanner`, `@content-strategist`, etc.
3. Inside Claude Code, ask: "run the content engine on
   `config/examples/fintech.yaml`". Claude will load the SKILL.md
   orchestrator, run `content-engine run`, and hand off to each
   subagent at the right stage.

The pipeline is interactive by design — you'll be prompted to pick a
candidate after the scan, and Claude will pause before the publisher
runs so you can review the draft.

## Schedule the morning scan

The `scan` stage is fully non-interactive — it fetches feeds, scores
them, and writes either JSON or a table. Wire it into cron, a systemd
timer, or a GitHub Actions schedule to get a daily candidate digest in
your inbox / Slack each morning.

Publish stays interactive on purpose — see [Why publish stays
interactive](#why-publish-stays-interactive) below.

### Slack digest via webhook

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"
content-engine scan --config config/examples/fintech.yaml --output table
```

`content-engine scan` reads `SLACK_WEBHOOK_URL` from the environment and
POSTs a formatted digest of the top candidates. You can also pass
`--notify-slack <url>` explicitly. Slack failures are non-fatal (the
scheduled job still exits 0), so a Slack outage won't poison your
morning.

### cron

Drop this into your crontab (`crontab -e`). Every weekday at 7:00 local
time, scan the fintech config and post the top candidates to Slack:

```cron
0 7 * * 1-5  cd /path/to/agentic-newsroom && \
  SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ" \
  /path/to/.venv/bin/content-engine scan \
    --config config/examples/fintech.yaml \
    --output json > "logs/scan-$(date +\%F).json"
```

The log file under `logs/` gives you an audit trail of what was surfaced
each day, useful for tuning `min_relevance_score` and your keyword list.

### GitHub Actions

`.github/workflows/morning-scan.yml`:

```yaml
name: morning-scan

on:
  schedule:
    - cron: "0 7 * * 1-5"   # 07:00 UTC, weekdays
  workflow_dispatch: {}

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e .
      - run: content-engine scan --config config/examples/fintech.yaml --output table
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

Add `SLACK_WEBHOOK_URL` as a repo secret. The Action runs without
human input and posts to Slack.

### Why publish stays interactive

The scan stage delivers ranked candidates. The strategist, asset
producer, and publisher stages stay interactive on purpose:

- **Picking the candidate** requires judgment the scoring rubric can't
  capture (saturation, brand fit, what you already said about the topic
  last week).
- **Reviewing the draft** is the place where context the agents don't
  have catches up with the output — corrections, tone tweaks, decisions
  about what to leave out.
- **Hitting publish** is irreversible-ish. A human gate is the cheapest
  defense against an agent confidently shipping something wrong.

Reactive content tied to real news, written by a system that can
produce 30 articles a day, is exactly the kind of system that needs a
human in the loop. Schedule the scan. Drive the rest yourself.

## CLI reference

```
content-engine scan      --config <cfg> [--output json|table] [--notify-slack <webhook>]
content-engine draft     prefetch --url <url> [--out <path>]
                         validate --draft <path>
                         slug "Some headline"
content-engine assets    og    --headline ... --slug ... --config ... --out ...
                         chart --slug ... --index N --title ... --kind bar|line|pie \
                                --data '[["Q1", 10], ["Q2", 20]]' --config ... --out ...
content-engine publish   --draft <d.json> --assets <a.json> --config <cfg> [--out <dir>] [--date YYYY-MM-DD]
content-engine run       --config <cfg> [--workdir <path> --resume]
```

Every subcommand emits machine-readable JSON to stdout when the agents
need to consume the output. Errors go to stderr.

## Config

Full schema is `config/schema.yaml`. The three top-level sections:

- **`company`** — name, industry, products, audience, tone, expertise
  areas, CTA, brand colors, optional logo. Used by the strategist for
  voice and by the asset producer for OG images.
- **`content`** — target keywords, RSS feeds, optional web-search
  queries, scan limits (`max_articles_per_run`, `min_relevance_score`,
  `date_range_days`).
- **`publishing`** — output directory, format (`mdx`/`md`), git settings,
  Next.js paths.

Three working examples live in `config/examples/`:

- `fintech.yaml` — small business lender (Fed/Bloomberg/Yahoo feeds).
- `healthcare-saas.yaml` — clinical workflow SaaS (HHS/HIMSS/Stat News).
- `ecommerce.yaml` — D2C retail platform (Retail Dive/Modern Retail).

Start by copying the closest match and editing.

### Tuning `min_relevance_score`

The scanner scores 0–100: keyword match (0–40) + source authority (0–20)
+ recency (0–20) + SEO potential (0–20). A tier-1 source (Reuters,
Bloomberg, FT, .gov) within the past 24 hours floors at ~40 with no
keyword hits. So:

- **30–45**: very permissive; useful when feeds are tightly curated.
- **50–60**: requires at least one keyword hit on top of source +
  recency. Good default.
- **65+**: requires multiple keyword hits or a niche feed reliably on
  topic. Raise to here once you've narrowed your feed list.

The schema default is 60. The fintech example uses 50 because broad
financial-news feeds rarely have headlines that hit niche SMB-lending
keywords.

## Architecture

### Why four agents

Each stage has different judgment criteria, different failure modes, and
different tools. Mashing them into one prompt would dilute every part.

- **news-scanner** has to be ruthless about cutting noise; one good
  candidate beats five mediocre ones.
- **content-strategist** has to write substance, not just rephrase the
  source. E-E-A-T (Experience, Expertise, Authoritativeness,
  Trustworthiness) is what Google rewards.
- **asset-producer** has to refuse to invent data. Charts must come from
  numbers in the article body, not made up.
- **publisher** has to obey hard git rules. Never `--no-verify`, never
  `git add -A`, never on `main`.

### Why a separate CLI

The agents don't fetch feeds, render PNGs, or parse YAML — that's
deterministic work where LLMs add cost and variance. The CLI:

- Fetches and scores feeds (`scanner.py`).
- Prefetches source articles into clean text and validates strategist
  drafts against hard SEO constraints (`strategist.py`).
- Renders OG images and charts via matplotlib (`assets.py`).
- Builds frontmatter + JSON-LD, renders MDX, validates the result,
  copies assets (`publisher.py`).

The agents call these as subprocesses or library functions. Result: each
agent prompt is short, the rules it must enforce are checked in code,
and the boundary between LLM and deterministic logic is explicit.

### Working directory layout

`content-engine run` creates per-article scratch space:

```
runs/<timestamp>/
  selected.json    # scanner pick
  brief.json       # prefetched source text
  draft.json       # strategist output (agent writes this)
  assets.json      # asset-producer manifest (agent writes this)
  assets/          # rendered OG + chart files
```

Each stage is idempotent. If a file exists, the pipeline advances. Re-enter
with `--workdir <path> --resume` after an agent has produced its file.

## Hard rules

These are non-negotiable. They live in the agent prompts, the validators,
and the CLI:

- **No fabricated facts, statistics, or quotes.** Every number in a chart
  must appear in the article body.
- **No copying >25 consecutive words from the source.** This is reactive
  analysis, not republishing.
- **No commits on `main`/`master`, no `git add -A`, no `--no-verify`,
  no force-push.** Publisher rule.
- **No invented URLs.** Scanner only emits URLs from feeds it actually
  fetched.
- **Always include source attribution.** Schema.org `isBasedOn` plus a
  visible "Originally reported by …" line in the article body.
- **Always pause for human review before publishing.** No autonomous
  publish path exists, by design.

## Output

The publisher writes a single MDX file with YAML frontmatter, ready for
Next.js MDX setups (Contentlayer, next-mdx-remote, the App Router's
built-in MDX support).

Frontmatter shape (camelCase for JS-friendliness):

```yaml
title: "What the Fed Cut Means for SMB Borrowers"
description: "..."
slug: "fed-cut-smb-borrowers"
date: "2026-05-08"
author: { name: "Acme Fintech", url: "https://acmefintech.com" }
keywords: ["interest rates", "small business loans", "SBA loans"]
schemaType: "Article"
readingTime: 4
ogImage: "/images/blog/fed-cut-smb-borrowers-og.png"
ogImageAlt: "..."
sourceAttribution: { url: "...", title: "...", publisher: "Federal Reserve" }
relatedLinks:
  - { anchorText: "...", target: "/blog/...", reason: "..." }
jsonLd:
  "@context": "https://schema.org"
  "@type": "Article"
  headline: "..."
  isBasedOn: { "@type": "CreativeWork", url: "...", name: "...", publisher: "..." }
```

The body has exactly one H1 (the headline), 2–4 H2 sections, and ends
with a CTA block if the strategist didn't include one.

JSON-LD lives in the frontmatter under `jsonLd`, not in a `<script>` tag.
Render it in your MDX layout component:

```tsx
<script
  type="application/ld+json"
  dangerouslySetInnerHTML={{ __html: JSON.stringify(post.jsonLd) }}
/>
```

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

89 tests cover scanner scoring, strategist validation, publisher render,
asset PNG dimensions, and the CLI orchestrator.

## License

MIT. See `LICENSE`.
