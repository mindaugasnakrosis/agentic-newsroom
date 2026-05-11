# LinkedIn post — content-engine launch

_Format note: LinkedIn doesn't render markdown. Copy the body below; the
linebreaks will survive as paragraph breaks. Strip the leading `#` headers
that follow — they're for editorial structure only._

---

The pattern I keep returning to when building agentic systems:

**Narrow agents. Deterministic glue. Strict JSON contracts. A human in the loop.**

I just shipped my 4th Claude Code plugin — content-engine — and the architecture is the same as the previous three, because it keeps working.

It turns trending industry news into publish-ready Next.js MDX articles. Four specialist agents:

→ **news-scanner** ranks RSS feeds and web search results
→ **content-strategist** writes original analysis with the news as a hook
→ **asset-producer** generates the OG image and any data charts
→ **publisher** renders MDX + JSON-LD, opens a PR

A Python CLI sits between them and does all the deterministic work — feed parsing, source-article prefetch, SEO validation, MDX rendering, image generation, asset copying, git operations. The agents do judgment; the code does pixels, files, and validation.

Three design decisions I'd carry into any agentic system:

**1. One agent per failure mode.** A news scanner needs to be ruthless about cutting noise. A content writer needs to refuse to fabricate stats. A publisher needs to obey hard git rules. Mashing those into one mega-prompt dilutes every part. Four narrow prompts > one wide one.

**2. Hard rules live in code, not just prompts.** "Never copy >25 consecutive words from the source" is in the strategist's prompt — but the validator enforces it. "Never commit on main, never --no-verify" is in the publisher's prompt — but the wrapper script refuses to. Prompts express intent; code makes intent unbreakable.

**3. Human review is a first-class stage, not a checkbox.** The pipeline explicitly pauses between draft and publish. No autonomous publish path exists. That's the difference between a tool I'd use and a tool I'd warn people about.

89 tests cover the pipeline. Most LLM workflows can't be tested; this one can, because the deterministic parts are extracted and the LLM parts have strict JSON output contracts.

If you're building agentic systems and finding yourself reaching for a bigger prompt, try the opposite — narrower agents, more code between them, a human gate before anything irreversible. It's the playbook I keep coming back to.

Repo + writeup in comments. Happy to dig into design questions.

#AI #Agents #ClaudeCode #LLMOps #SoftwareEngineering
