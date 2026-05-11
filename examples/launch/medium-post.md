# I built a multi-agent AI system that reads industry news and writes original articles about it

_Four specialized agents, strict JSON contracts between them, and a human review gate before anything ships. The architecture that finally made my agentic systems work in production._

Every morning, four AI agents read the news for me. The first one ranks the day's RSS feeds and surfaces the three stories worth writing about. I pick one. The second agent reads the source article and writes a 1,000-word piece of original analysis from my company's perspective — headline, meta description, slug, structured markdown body, internal-link suggestions, and a schema.org type, all conforming to a strict JSON schema. The third generates a 1200×630 social card and, if the body contains real numeric data, one or two charts to go with it. The fourth renders the final MDX file with embedded JSON-LD, copies the assets into my Next.js public tree, opens a feature branch, and creates a pull request.

I review the draft before the assets and publisher stages run. There is no autonomous publish path.

This is my 4th Claude Code plugin. The architecture is the same as the previous three because it keeps working: **narrow agents with strict contracts, deterministic code between them, a human gate before anything irreversible.** This post walks through the most recent one — **content-engine** — and the five design decisions I now reach for by default whenever I'm building agentic systems.

## The architecture

![Four-agent content-engine pipeline: news-scanner ranks RSS feeds, content-strategist writes original analysis, asset-producer generates the OG image and charts, publisher renders MDX with JSON-LD and opens a git PR. Human review gates sit between scanner and strategist, and between strategist and asset-producer. A Python CLI underneath handles all deterministic boundary work.](architecture.png)

Each box is a Claude Code subagent. Each arrow is a JSON file written to a per-article working directory. A Python CLI (`content-engine`) sits underneath and does every deterministic operation the agents would otherwise have to bluff their way through — RSS feed parsing and scoring, source-article prefetch and cleaning, SEO constraint validation, MDX rendering, OG-image generation (matplotlib, 1200×630), schema.org JSON-LD assembly, asset copying into the Next.js public tree.

## Decision 1: One agent per failure mode

The first temptation with an LLM pipeline is to ship one agent and give it tools. That's wrong because **different stages of a content pipeline have different failure modes**, and prompt language that prevents one failure makes another worse.

The news-scanner has to be ruthless about cutting noise. One good candidate beats five mediocre ones. Its prompt is full of language like "if you're unsure, drop it" and a strict 0–100 scoring rubric.

The content-strategist has to write substance. Vague summaries of the source article are the failure mode. Its prompt is full of language like "the news is the hook; your expertise is the substance" and explicit instructions about original analysis, not paraphrasing.

The asset-producer has to refuse to invent data. The failure mode is drawing a chart from numbers it imagined. Its prompt has the hard rule "every number in a chart must appear in the article body."

The publisher has to obey git discipline. The failure mode is `git push --force` on main. Its prompt has explicit prohibitions on `--no-verify`, `git add -A`, and committing on `main`/`master`.

If you put all four sets of instructions in one prompt, they fight each other. "Be ruthless" conflicts with "write substantively." "Never invent data" gets diluted by 50 other rules. **Four narrow prompts of 100 lines each are more reliable than one 400-line prompt covering the same ground.**

## Decision 2: Deterministic code between the agents

The second insight took me longer to learn: **most of what looks like "agent work" is actually deterministic work the agent shouldn't be doing.**

When the news-scanner runs, it doesn't fetch RSS feeds. The CLI does. The scanner reads the structured candidate list the CLI produced and applies judgment on top — re-ranking, picking angles, dropping items the rubric scored too generously.

When the content-strategist runs, it doesn't parse HTML from the source article. The CLI does (BeautifulSoup, strips scripts/styles/nav, caps at 20K chars). The strategist reads clean structured text and writes.

When the asset-producer runs, it doesn't render PNGs. The CLI does (matplotlib, with hard checks on chart kind and slice counts). The agent decides what to render and writes the alt text; the code produces the pixels.

When the publisher runs, it doesn't assemble JSON-LD or YAML frontmatter or copy image files. The CLI does. The agent invokes the render command and then handles git on a feature branch.

The result is that **each agent's prompt is short** (under 200 lines), each prompt is **about judgment, not mechanics**, and the **boundary between LLM and deterministic logic is explicit** — you can read the CLI code to know exactly what cannot vary, and read the prompt to know exactly what's left to judgment.

This is the most important design decision in the whole project. If I had to give one piece of advice to someone building an agentic system, it's: **before adding to a prompt, ask whether the work belongs in code.**

## Decision 3: Strict JSON contracts as the agent interface

Agents communicate by writing JSON files to a working directory, not by passing messages in context.

```
runs/20260508-141522/
  selected.json    # scanner's pick
  brief.json       # prefetched source text
  draft.json       # strategist's output
  assets.json      # asset-producer's manifest
```

Each file has a strict schema. The strategist's draft must include `headline ≤60 chars`, `meta_description ≤155 chars`, `slug` matching `^[a-z0-9]+(-[a-z0-9]+)*$`, `target_keywords` count 3–5, `schema_type` in `{Article, NewsArticle, BlogPosting}`, zero H1 in the body. The validator runs as a separate stage and returns a list of `Issue` objects with `level: error | warning`. Errors block; warnings inform.

This buys three things:

1. **Each stage is independently re-runnable.** If the asset producer fails, I rerun just the asset producer. I don't re-invoke the strategist or re-scan the feeds.
2. **Each stage is independently testable.** Hand it a known-good JSON input and assert on the output. I have 89 tests for this pipeline. Most LLM workflows can't be tested at all.
3. **Each stage is debuggable.** When something looks wrong in the final MDX, I can read the four JSON files in the working directory and pinpoint where reality diverged from expectation.

The interface between LLM and code is not natural language. It's a JSON schema, validated.

## Decision 4: Hard rules in code, not just prompts

A prompt that says "never copy more than 25 consecutive words from the source" is a polite request. A validator that scans the draft body and refuses to mark it `ok: true` if it finds a long verbatim quote is a hard rule.

content-engine encodes the hard rules in both places, on purpose. The prompt expresses intent — that's what gets the LLM to write the right kind of text in the first place. The validator is the safety net that catches the cases where the prompt didn't work.

Same with git: the publisher agent's prompt says "never `--no-verify`, never `git add -A`, never on main/master." But the practical safety comes from the fact that those operations require the human running Claude Code to approve them.

**Prompts express intent. Code makes intent unbreakable.** Use both.

## Decision 5: A human gate before anything irreversible

There is no autonomous publish path. The pipeline explicitly stops after the strategist writes the draft. The orchestrator skill says, in plain English, "Always pause for human review before publishing. No autonomous publish."

I have strong views on this. Reactive content tied to real news, written by a system that can produce 30 articles a day, is exactly the kind of system that needs a human in the loop. Not because the LLM might write something incorrect (it might), but because **automation at scale magnifies whatever you encode** — including the things you didn't realize you were encoding. The human gate is the place where context the agents don't have ("we said the opposite of this two weeks ago", "this lender just lost a major lawsuit") catches up with the output.

This is the difference between a tool I'd use to ship work and a tool I'd warn people about.

## What I'd carry to the next agentic project

Looking back across the four Claude Code plugins I've built — md-to-jira, azure-cost-investigator, a Notion spec checker, and now content-engine — these are the moves I keep making:

- **Many narrow agents, not one wide one.** Each agent should have a single failure mode it's tuned against.
- **Deterministic CLI doing the boundary work.** Anything reproducible should be in code, not in a prompt.
- **JSON contracts between stages.** Files in a working directory, not passing context in-context.
- **Hard rules in code AND prompts.** Belt and suspenders.
- **A human gate before anything irreversible.** Not optional.
- **Test it.** The deterministic parts are testable; extract them, write the tests.

89 tests covering an LLM pipeline isn't a stunt. It's the natural consequence of pulling the deterministic work out of the agent layer. The agents shrink. The code grows. Both get more reliable. The system survives contact with production.

That's the playbook.

---

_The repo is at [github.com/mindaugasnakrosis/agentic-newsroom](https://github.com/mindaugasnakrosis/agentic-newsroom). It ships as a Claude Code plugin: drop it into a repo, configure your industry keywords and RSS feeds, run `content-engine run`, and a working pipeline drops PRs into your blog repo. I'm always interested in talking to people building agentic systems — find me at mindaugasm@intelme.ai._
