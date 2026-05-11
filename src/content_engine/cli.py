"""content-engine — top-level CLI that ties the four-agent pipeline together.

This is the entry point installed by `pip install content-engine`. The
heavy lifting lives in the per-stage modules:

    scanner.py     — RSS scoring               -> `content-engine scan`
    strategist.py  — prefetch + validate        -> `content-engine draft`
    assets.py      — OG image + charts          -> `content-engine assets`
    publisher.py   — MDX + JSON-LD render       -> `content-engine publish`

Plus a `run` command that walks a human through the pipeline interactively,
creating a per-article working directory and printing the next-step
instruction at each handoff to a Claude Code agent.

The CLI is deterministic. It does not call an LLM. The agent calls
(news-scanner, content-strategist, asset-producer, publisher) happen in
Claude Code, with this CLI as their hands.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml

from content_engine import assets as assets_mod
from content_engine import publisher as publisher_mod
from content_engine import scanner as scanner_mod
from content_engine import strategist as strategist_mod


# --- Helpers ---------------------------------------------------------------


def _load_yaml(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise click.ClickException(f"Config at {path} must be a YAML mapping.")
    return data


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _working_dir(base: Path, slug_hint: str | None = None) -> Path:
    """Create a per-run working directory under base/runs/<timestamp>-<hint>."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{slug_hint}" if slug_hint else stamp
    path = base / "runs" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- Top-level group -------------------------------------------------------


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="content-engine", prog_name="content-engine")
def cli() -> None:
    """Multi-agent SEO content pipeline. Run `content-engine run --help` to start."""


# --- scan ------------------------------------------------------------------


@cli.command("scan")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    type=click.Choice(["json", "table"]),
    default="json",
    show_default=True,
)
def cmd_scan(config_path: str, output: str) -> None:
    """Score RSS feeds and emit ranked candidates."""
    config = _load_yaml(config_path)
    candidates = scanner_mod.scan(config)

    if output == "json":
        _emit_json([asdict(c) for c in candidates])
        return
    if not candidates:
        click.echo("(no candidates above min_relevance_score)")
        return
    for c in candidates:
        click.echo(f"[{c.relevance_score:>3}] {c.title}")
        click.echo(f"        {c.source}  {c.published_date or '?'}  {c.url}")


# --- draft -----------------------------------------------------------------


@cli.group("draft")
def cmd_draft() -> None:
    """Prefetch source articles and validate strategist drafts."""


@cmd_draft.command("prefetch")
@click.option("--url", required=True)
@click.option("--out", "out_path", type=click.Path(dir_okay=False), help="Write JSON here instead of stdout.")
def cmd_draft_prefetch(url: str, out_path: str | None) -> None:
    """Fetch and clean a source URL into structured JSON the strategist agent consumes."""
    result = strategist_mod.prefetch_article(url)
    if out_path:
        Path(out_path).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        click.echo(out_path)
    else:
        _emit_json(result)
    if result.get("status") != "ok":
        sys.exit(1)


@cmd_draft.command("validate")
@click.option("--draft", "draft_path", required=True, type=click.Path(exists=True, dir_okay=False))
def cmd_draft_validate(draft_path: str) -> None:
    """Validate a strategist draft JSON file. Exit 0 if no errors, 1 otherwise."""
    draft = _load_json(draft_path)
    issues = strategist_mod.validate_draft(draft)
    payload = {
        "ok": not any(i.level == "error" for i in issues),
        "issues": [i.as_dict() for i in issues],
    }
    _emit_json(payload)
    sys.exit(0 if payload["ok"] else 1)


@cmd_draft.command("slug")
@click.argument("text")
def cmd_draft_slug(text: str) -> None:
    """Print a URL-safe slug derived from arbitrary text."""
    click.echo(strategist_mod.slugify(text))


# --- assets ----------------------------------------------------------------


@cli.group("assets")
def cmd_assets() -> None:
    """Render OG images and charts."""


@cmd_assets.command("og")
@click.option("--headline", required=True)
@click.option("--slug", required=True)
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "out_dir", required=True, type=click.Path(file_okay=False))
def cmd_assets_og(headline: str, slug: str, config_path: str, out_dir: str) -> None:
    """Render a 1200x630 OG image."""
    config = _load_yaml(config_path)
    out = assets_mod.render_og_image(headline, slug, config, out_dir)
    _emit_json(
        {
            "filename": out.name,
            "type": "og-image",
            "alt_text": "",
            "path": str(out.resolve()),
        }
    )


@cmd_assets.command("chart")
@click.option("--slug", required=True)
@click.option("--index", type=int, required=True)
@click.option("--title", required=True)
@click.option("--kind", type=click.Choice(["bar", "line", "pie"]), default="bar", show_default=True)
@click.option("--data", "data_json", required=True, help='JSON array of [label, value] pairs.')
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "out_dir", required=True, type=click.Path(file_okay=False))
def cmd_assets_chart(
    slug: str, index: int, title: str, kind: str, data_json: str, config_path: str, out_dir: str
) -> None:
    """Render a small data chart from inline JSON data."""
    try:
        raw = json.loads(data_json)
    except json.JSONDecodeError as ex:
        raise click.ClickException(f"--data is not valid JSON: {ex}")
    if not isinstance(raw, list) or not all(isinstance(p, list) and len(p) == 2 for p in raw):
        raise click.ClickException("--data must be a JSON array of [label, value] pairs.")

    config = _load_yaml(config_path)
    try:
        out = assets_mod.render_chart(
            data=[(p[0], p[1]) for p in raw],
            title=title,
            kind=kind,
            slug=slug,
            index=index,
            config=config,
            out_dir=out_dir,
        )
    except ValueError as ex:
        raise click.ClickException(str(ex))

    _emit_json(
        {
            "filename": out.name,
            "type": "chart",
            "alt_text": "",
            "path": str(out.resolve()),
        }
    )


# --- publish ---------------------------------------------------------------


@cli.command("publish")
@click.option("--draft", "draft_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--assets", "assets_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "out_dir", type=click.Path(file_okay=False), help="Override publishing.output_dir.")
@click.option("--date", "publish_date", help="Override publish date (YYYY-MM-DD).")
def cmd_publish(
    draft_path: str,
    assets_path: str | None,
    config_path: str,
    out_dir: str | None,
    publish_date: str | None,
) -> None:
    """Render a draft + assets into an MDX file (no git side effects)."""
    draft = _load_json(draft_path)
    assets = _load_json(assets_path) if assets_path else []
    config = _load_yaml(config_path)
    result = publisher_mod.render_article(
        draft, assets, config, out_dir=out_dir, publish_date=publish_date
    )
    _emit_json(result.as_dict())
    sys.exit(0 if result.ok else 1)


# --- run -------------------------------------------------------------------


_NEXT_STEP_DRAFT = """\
Next step — invoke the content-strategist agent in Claude Code.

  Tell the agent:
    - Source brief is at: {brief_path}
    - Config is at:       {config_path}
    - Save the draft JSON to: {draft_path}

When the draft file exists, re-run:

    content-engine run --config {config_path} --workdir {workdir} --resume

"""

_NEXT_STEP_ASSETS = """\
Next step — invoke the asset-producer agent in Claude Code.

  Tell the agent:
    - Validated draft is at: {draft_path}
    - Config is at:          {config_path}
    - Write the manifest JSON to: {assets_path}
    - Write image files to:       {assets_dir}

When the manifest file exists, re-run:

    content-engine run --config {config_path} --workdir {workdir} --resume

"""

_NEXT_STEP_PUBLISH = """\
Article rendered.

  MDX:           {mdx_path}
  Assets copied: {assets_count} file(s)

Next step — invoke the publisher agent in Claude Code to commit on a feature
branch and (optionally) open a PR. The agent's hard rules forbid committing
on main/master, force-push, or skipping hooks. Do not bypass them.
"""


@cli.command("run")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--workdir",
    type=click.Path(file_okay=False),
    help="Reuse an existing run dir (advances to the next stage automatically).",
)
@click.option("--resume", is_flag=True, help="With --workdir, advance through any already-completed stages.")
def cmd_run(config_path: str, workdir: str | None, resume: bool) -> None:
    """Walk through scan -> draft -> assets -> publish, pausing at each agent handoff.

    Each stage writes its output into the working directory. When the next
    file the pipeline expects already exists, this command advances to the
    following stage; otherwise it prints instructions and exits so the
    relevant agent can do its part.
    """
    config = _load_yaml(config_path)

    base = Path(config_path).resolve().parent
    if workdir:
        wd = Path(workdir).resolve()
        if not wd.exists():
            raise click.ClickException(f"Working dir does not exist: {wd}")
    else:
        wd = _working_dir(base)

    selected_path = wd / "selected.json"
    brief_path = wd / "brief.json"
    draft_path = wd / "draft.json"
    assets_dir = wd / "assets"
    assets_manifest = wd / "assets.json"

    # --- Stage 1: scan + pick -------------------------------------------------
    if not selected_path.exists():
        click.echo(f"[1/4] Scanning RSS feeds defined in {config_path} ...")
        candidates = scanner_mod.scan(config)
        if not candidates:
            raise click.ClickException(
                "No candidates above min_relevance_score. Lower the threshold "
                "in your config, broaden keywords, or check that feed URLs are reachable."
            )

        click.echo("")
        click.echo("Top candidates:")
        for i, c in enumerate(candidates, start=1):
            click.echo(f"  {i:>2}. [{c.relevance_score:>3}] {c.title}")
            click.echo(f"        {c.source}  {c.published_date or '?'}")
            click.echo(f"        {c.url}")

        if resume:
            raise click.ClickException(
                "No selection has been made yet. Run without --resume to pick interactively, "
                "or write a `selected.json` to the workdir manually."
            )

        choice = click.prompt(
            "\nWhich candidate? (1-N, or 0 to abort)",
            type=click.IntRange(0, len(candidates)),
        )
        if choice == 0:
            raise click.ClickException("Aborted.")
        selected = candidates[choice - 1]
        selected_path.write_text(
            json.dumps(asdict(selected), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        click.echo(f"Saved selection: {selected_path}")

    selected = _load_json(selected_path)

    # --- Stage 2: prefetch + draft ------------------------------------------
    if not brief_path.exists():
        click.echo(f"[2/4] Prefetching source: {selected['url']}")
        brief = strategist_mod.prefetch_article(selected["url"])
        if brief.get("status") != "ok":
            raise click.ClickException(
                f"Source prefetch failed: {brief.get('error', 'unknown error')}. "
                "Pick a different candidate, or fetch the article body manually and "
                "write a brief.json with the same shape."
            )
        # Stash the scanner's suggested angle alongside the source for the agent.
        brief["scanner_candidate"] = selected
        brief_path.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
        click.echo(f"Saved brief: {brief_path}")

    if not draft_path.exists():
        click.echo("")
        click.echo(
            _NEXT_STEP_DRAFT.format(
                brief_path=brief_path,
                config_path=config_path,
                draft_path=draft_path,
                workdir=wd,
            )
        )
        return

    draft = _load_json(draft_path)
    issues = strategist_mod.validate_draft(draft)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        click.echo("Draft has validation errors:")
        for i in errors:
            click.echo(f"  - [{i.field}] {i.message}")
        raise click.ClickException(
            "Fix the draft (re-run the strategist agent) and try again."
        )
    warnings = [i for i in issues if i.level == "warning"]
    if warnings:
        click.echo("Draft warnings (non-blocking):")
        for i in warnings:
            click.echo(f"  - [{i.field}] {i.message}")

    # --- Stage 3: assets -----------------------------------------------------
    if not assets_manifest.exists():
        assets_dir.mkdir(parents=True, exist_ok=True)
        click.echo("")
        click.echo(
            _NEXT_STEP_ASSETS.format(
                draft_path=draft_path,
                config_path=config_path,
                assets_path=assets_manifest,
                assets_dir=assets_dir,
                workdir=wd,
            )
        )
        return

    assets = _load_json(assets_manifest)
    if not isinstance(assets, list):
        raise click.ClickException(
            f"{assets_manifest} must be a JSON array of asset objects."
        )

    # --- Stage 4: render -----------------------------------------------------
    click.echo("[4/4] Rendering MDX ...")
    result = publisher_mod.render_article(draft, assets, config)
    click.echo(
        _NEXT_STEP_PUBLISH.format(
            mdx_path=result.mdx_path,
            assets_count=len(result.assets_copied),
        )
    )
    if result.issues:
        click.echo("Render-time issues:")
        for issue in result.issues:
            click.echo(f"  - [{issue['level']}] {issue['field']}: {issue['message']}")
    sys.exit(0 if result.ok else 1)


# --- Entry point -----------------------------------------------------------


def main() -> None:
    """Console-script entry point declared in pyproject.toml."""
    cli()


if __name__ == "__main__":
    main()
