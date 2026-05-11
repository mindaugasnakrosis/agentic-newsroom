---
name: content-engine
description: Multi-agent pipeline that turns trending industry news into publish-ready Next.js MDX articles. Orchestrates four specialist agents — news-scanner, content-strategist, asset-producer, publisher — with deterministic CLI tooling between them and a human review gate before publish. Use when the user wants to ship reactive, SEO-optimized content tied to a real news hook, or asks for "an article about X" / "react to this news" / "blog post on the latest in <industry>".
---

# Content Engine

Four-stage pipeline:

1. **news-scanner** finds newsworthy hooks (RSS + web search, scored).
2. **content-strategist** writes ORIGINAL analysis with the news as a hook.
3. **asset-producer** generates the OG image + any data charts.
4. **publisher** renders the MDX file, copies assets, opens a PR.

A human reviews between stages 2 and 3. The CLI (`content-engine`) is the
deterministic spine each agent calls; the agents do judgment, the CLI does
files and pixels.

## When to use this skill

The user wants to **publish content tied to recent industry news**. Trigger
phrases:

- "write a blog post about the recent X"
- "what's happening in <industry> this week worth writing about?"
- "draft an article reacting to <news event>"
- "run the content engine on <topic>"

Do **not** use this skill for:

- Generic content writing with no news hook (just write the markdown).
- Updating an existing article (edit the MDX directly).
- Content the user has already drafted themselves and just wants published
  (skip to the publisher agent directly).

## Prerequisites

Before invoking the pipeline, confirm:

1. A config YAML exists. Examples live in `config/examples/` (fintech,
   healthcare-saas, ecommerce). If none, ask the user which industry and
   copy the closest example, then collaborate on edits.
2. The `content-engine` CLI is installed: `pip install -e .` from the
   plugin root, or it's already on PATH from a prior session.
3. The Next.js repo's `content/blog/` (or whatever `publishing.output_dir`
   points at) is present and writable.

## How to run the pipeline

The fast path is `content-engine run --config <path>`. It walks the user
through every stage, creating a per-article working directory and pausing
at each agent handoff with explicit next-step instructions.

```
content-engine run --config config/examples/fintech.yaml
```

Stage-by-stage breakdown follows. Each stage is also runnable on its own —
useful when re-trying a single step or scripting.

### Stage 1 — Scan

```
content-engine scan --config <path> --output table
```

Returns ranked candidates. The CLI scores deterministically (keyword match
+ source authority + recency + headline length). The **news-scanner agent**
should re-rank using judgment the rubric can't capture (angle quality,
saturation, brand fit) and propose the top 3-5 to the user. See
`agents/news-scanner.md` for the agent's full instructions.

When `content-engine run` is in use, this stage prompts the user to pick
one candidate and saves the choice to the working dir.

### Stage 2 — Draft

The strategist needs:

- The selected candidate's URL.
- A clean text dump of the source article (use `content-engine draft
  prefetch --url <url>`).
- The config (for company voice, target keywords, CTA).

Hand off to the **content-strategist agent** (`agents/content-strategist.md`).
It returns a JSON draft. Validate before continuing:

```
content-engine draft validate --draft <path>
```

Validation enforces hard SEO constraints (headline ≤60 chars, meta ≤155,
slug shape, schema.org type, keyword count 3-5, no H1 in body). Errors
block; warnings inform.

**Always pause here for human review.** The user reads the draft, edits if
needed, and explicitly says "go" before the asset/publish stages run. This
is the gate that keeps reactive content honest.

### Stage 3 — Assets

Hand off to the **asset-producer agent** (`agents/asset-producer.md`). It
calls `content-engine assets og` (always) and optionally `content-engine
assets chart` (only if the article body contains real numeric data),
returns a JSON manifest with `filename`, `type`, `alt_text`, `path`.

The agent never invents chart data. If the body has no real numbers, the
manifest contains only the OG image and a hero-image description.

### Stage 4 — Publish

Hand off to the **publisher agent** (`agents/publisher.md`). It runs:

```
content-engine publish --draft <draft.json> --assets <assets.json> --config <cfg>
```

…which renders MDX + JSON-LD, copies images into the Next.js public tree,
and validates the result. Then the agent does the git work on a feature
branch (never on main, never `--no-verify`, never `git add -A`). It opens
a PR via `gh` if available.

## Working directory layout

`content-engine run` creates per-article scratch space:

```
runs/<timestamp>/
  selected.json    # scanner pick
  brief.json       # prefetched source text
  draft.json       # strategist output (you write this via the agent)
  assets.json      # asset-producer manifest (you write this via the agent)
  assets/          # rendered OG + chart files
```

Each stage is idempotent — if a file already exists, the pipeline advances
to the next stage. Re-enter with `--workdir <path> --resume` after an
agent has produced its file.

## Config in one paragraph

A config YAML has three top-level sections: `company` (name, voice,
brand_colors, cta_url, cta_text, logo_path), `content` (industry,
keywords, sources.rss_feeds, date_range_days, min_relevance_score,
max_articles_per_run), and `publishing` (output_dir, canonical_base,
nextjs.image_dir, git settings). Full schema is in `config/schema.yaml`.
Working examples in `config/examples/`. Lower `min_relevance_score` if
scans return zero candidates.

## Hard rules across all agents

These are non-negotiable. If you (the orchestrator) notice any agent
about to violate them, stop and ask the user.

- **Never fabricate facts, statistics, or quotes.** Every number in a
  chart must appear in the article body. Every fact in the body must be
  defensible from the source or the company's stated knowledge.
- **Never copy >25 consecutive words from the source article.** This is
  reactive analysis, not republishing.
- **Never commit on `main`/`master`, never `git add -A`, never
  `--no-verify`, never force-push.** The publisher's hard rules.
- **Never invent URLs.** Scanner only emits URLs from feeds it actually
  fetched.
- **Always include source attribution.** Schema.org `isBasedOn` plus a
  visible "Originally reported by …" line in the article body.
- **Pause for human review before publishing.** No autonomous publish.

## Failure modes and recovery

- **Scan returns zero candidates.** Lower `min_relevance_score` (default
  60 is strict for tier-1 sources without keyword hits) or broaden
  keywords. Tier-1 sources floor around 45 without matches.
- **Source prefetch fails.** Pick a different candidate. If the user
  insists on the original, ask them to paste the article text and write
  `brief.json` manually.
- **Validation errors on the draft.** Re-invoke the strategist with the
  list of errors. Don't hand-edit — the strategist owns this content.
- **Brand colors fail contrast in the OG image.** Asset producer falls
  back to black/white and adds `_warnings` to the manifest. Surface that
  warning to the user before publish.
- **`content-engine publish` reports `ok: false`.** Read the `issues`
  array. Common cause: the body references an image filename the asset
  producer didn't actually emit. Re-run asset producer or remove the
  reference from the body.

## Quick reference — CLI commands

```
content-engine scan --config <cfg> [--output json|table]
content-engine draft prefetch --url <url> [--out <path>]
content-engine draft validate --draft <path>
content-engine draft slug "Some headline"
content-engine assets og --headline ... --slug ... --config ... --out ...
content-engine assets chart --slug ... --index N --title ... --kind bar|line|pie \
                            --data '[["Q1", 10], ["Q2", 20]]' --config ... --out ...
content-engine publish --draft <d.json> --assets <a.json> --config <cfg> [--out <dir>]
content-engine run --config <cfg> [--workdir <path> --resume]
```

## Pointers

- `agents/news-scanner.md` — full system prompt and scoring rubric.
- `agents/content-strategist.md` — JSON output schema, SEO constraints,
  E-E-A-T expectations.
- `agents/asset-producer.md` — when to draw a chart, alt-text rules.
- `agents/publisher.md` — git rules, PR template, schema.org JSON-LD.
- `config/schema.yaml` — every config field with description and default.
- `config/examples/` — fintech, healthcare-saas, ecommerce starters.
- `templates/nextjs-article/` — MDX skeleton + OG-image upgrade path docs.
