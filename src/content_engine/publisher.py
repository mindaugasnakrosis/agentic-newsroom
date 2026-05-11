"""Publisher — renders a strategist draft into MDX + JSON-LD, writes to disk.

The agent (`agents/publisher.md`) wraps this module and handles git side
effects. This file owns the deterministic rendering boundary: build
frontmatter, build the JSON-LD object, render the Jinja template, copy
assets, and validate the final MDX.

CLI usage:
    python -m content_engine.publisher render \\
        --draft drafts/article.json \\
        --assets assets/article.json \\
        --config config/examples/fintech.yaml \\
        --out content/blog

Library usage:
    from content_engine.publisher import render_article, validate_mdx
    summary = render_article(draft, assets, config, out_dir)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date as date_cls
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import frontmatter
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from content_engine.strategist import Issue, reading_time_minutes


# Resolve the bundled template directory regardless of how the package
# was installed (editable, wheel, zip).
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "nextjs-article"


# --- Helpers ---------------------------------------------------------------


_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+", re.MULTILINE)


def _company_url(config: dict[str, Any]) -> str:
    """Best-effort guess at the company's site origin from cta_url."""
    cta = (config.get("company") or {}).get("cta_url") or ""
    parsed = urlparse(cta)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _today_iso() -> str:
    return date_cls.today().isoformat()


def _public_image_path(filename: str, image_dir: str) -> str:
    """Convert a Next.js public image dir + filename to a URL-style path.

    Next.js serves `public/<x>` at `/<x>`. So `public/images/blog/foo.png`
    is referenced in MDX as `/images/blog/foo.png`. Strip a leading
    `public/` if present.
    """
    parts = Path(image_dir).parts
    if parts and parts[0] in ("public", "./public"):
        parts = parts[1:]
    rel = "/".join(parts)
    return f"/{rel}/{filename}".replace("//", "/")


def _has_cta(body: str, cta_url: str, cta_text: str) -> bool:
    """Heuristic: does the body already contain the CTA?"""
    if cta_url and cta_url in body:
        return True
    if cta_text and cta_text.lower() in body.lower():
        return True
    return False


def _build_cta_block(config: dict[str, Any]) -> str:
    """Render the CTA appended after the body if the strategist forgot it."""
    company = config.get("company") or {}
    cta_url = company.get("cta_url") or ""
    cta_text = company.get("cta_text") or ""
    if not cta_url or not cta_text:
        return ""
    return f"## Ready to take the next step?\n\n[{cta_text}]({cta_url})"


# --- Frontmatter + JSON-LD builders ---------------------------------------


def build_jsonld(
    draft: dict[str, Any],
    config: dict[str, Any],
    og_image_public_path: str | None,
    publish_date: str,
) -> dict[str, Any]:
    """Build a schema.org JSON-LD object for the article.

    Mirrors templates/nextjs-article/schema-ld.json — keep that file in
    sync with this function so the documented shape stays honest.
    """
    company = config.get("company") or {}
    publishing = config.get("publishing") or {}
    canonical_base = publishing.get("canonical_base") or _company_url(config)
    canonical_url = (
        f"{canonical_base.rstrip('/')}/blog/{draft['slug']}" if canonical_base else f"/blog/{draft['slug']}"
    )
    company_url = _company_url(config)

    publisher_block: dict[str, Any] = {
        "@type": "Organization",
        "name": company.get("name") or "",
    }
    if company.get("logo_path"):
        publisher_block["logo"] = {
            "@type": "ImageObject",
            "url": company["logo_path"],
        }

    jsonld: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": draft.get("schema_type") or "Article",
        "headline": draft["headline"],
        "description": draft["meta_description"],
        "datePublished": publish_date,
        "dateModified": publish_date,
        "author": {
            "@type": "Organization",
            "name": company.get("name") or "",
            "url": company_url,
        },
        "publisher": publisher_block,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": canonical_url,
        },
        "keywords": list(draft.get("target_keywords") or []),
    }
    if og_image_public_path:
        jsonld["image"] = og_image_public_path

    src = draft.get("source_attribution") or {}
    if src.get("url"):
        jsonld["isBasedOn"] = {
            "@type": "CreativeWork",
            "url": src["url"],
            "name": src.get("title") or "",
            "publisher": src.get("publisher") or "",
        }

    return jsonld


def build_frontmatter(
    draft: dict[str, Any],
    assets: list[dict[str, Any]],
    config: dict[str, Any],
    publish_date: str | None = None,
) -> dict[str, Any]:
    """Assemble the frontmatter dict that gets YAML-dumped into the MDX."""
    publish_date = publish_date or _today_iso()
    company = config.get("company") or {}
    publishing = config.get("publishing") or {}
    nextjs = publishing.get("nextjs") or {}
    image_dir = nextjs.get("image_dir") or "public/images/blog"

    og_asset = next((a for a in assets if a.get("type") == "og-image"), None)
    hero_asset = next((a for a in assets if a.get("type") == "hero-image"), None)

    og_public_path = (
        _public_image_path(og_asset["filename"], image_dir) if og_asset else None
    )
    hero_public_path = (
        _public_image_path(hero_asset["filename"], image_dir) if hero_asset else None
    )

    body = draft.get("article_body") or ""
    declared_rt = draft.get("estimated_reading_time")
    reading_time = (
        declared_rt if isinstance(declared_rt, int) and declared_rt > 0 else reading_time_minutes(body)
    )

    fm: dict[str, Any] = {
        "title": draft["headline"],
        "description": draft["meta_description"],
        "slug": draft["slug"],
        "date": publish_date,
        "author": {
            "name": company.get("name") or "",
            "url": _company_url(config),
        },
        "keywords": list(draft.get("target_keywords") or []),
        "schemaType": draft.get("schema_type") or "Article",
        "readingTime": reading_time,
    }
    if og_public_path:
        fm["ogImage"] = og_public_path
        fm["ogImageAlt"] = og_asset.get("alt_text") or draft["headline"]
    if hero_public_path:
        fm["heroImage"] = hero_public_path
        fm["heroImageAlt"] = hero_asset.get("alt_text") or draft["headline"]

    src = draft.get("source_attribution") or {}
    if src:
        fm["sourceAttribution"] = {
            "url": src.get("url") or "",
            "title": src.get("title") or "",
            "publisher": src.get("publisher") or "",
        }

    related = draft.get("suggested_internal_links") or []
    if related:
        fm["relatedLinks"] = [
            {
                "anchorText": link.get("anchor_text", ""),
                "target": link.get("target", ""),
                "reason": link.get("reason", ""),
            }
            for link in related
            if isinstance(link, dict)
        ]

    fm["jsonLd"] = build_jsonld(draft, config, og_public_path, publish_date)

    return fm


# --- Rendering -------------------------------------------------------------


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def render_mdx(
    draft: dict[str, Any],
    assets: list[dict[str, Any]],
    config: dict[str, Any],
    publish_date: str | None = None,
) -> str:
    """Render the final MDX text. Pure function — does not touch the filesystem."""
    fm = build_frontmatter(draft, assets, config, publish_date=publish_date)
    yaml_text = yaml.safe_dump(
        fm,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,  # don't auto-wrap long strings; readers expect single-line meta
    )

    body = draft["article_body"]
    # Normalize so the body always has exactly one trailing newline. Agents
    # vary, and the CTA spacing in template.mdx assumes a single trailing
    # newline — without this, a draft ending in `\n\n` would print a stray
    # blank line above the CTA.
    body = body.rstrip("\n") + "\n"
    cta_url = (config.get("company") or {}).get("cta_url") or ""
    cta_text = (config.get("company") or {}).get("cta_text") or ""
    cta_block = "" if _has_cta(body, cta_url, cta_text) else _build_cta_block(config)

    env = _jinja_env()
    template = env.get_template("template.mdx")
    return template.render(
        frontmatter_yaml=yaml_text,
        headline=draft["headline"],
        body=body,
        cta_block=cta_block,
    )


# --- Validation ------------------------------------------------------------


def validate_mdx(
    rendered: str,
    expected_slug: str,
    expected_headline: str,
    available_image_paths: set[str] | None = None,
) -> list[Issue]:
    """Final paranoia checks on the rendered MDX file.

    available_image_paths: the set of public image paths the publisher
    actually copied into place. Body-level image references that don't
    appear here become errors.
    """
    issues: list[Issue] = []

    try:
        post = frontmatter.loads(rendered)
    except Exception as ex:
        return [Issue("error", "_root", f"Frontmatter parse failed: {ex.__class__.__name__}: {ex}")]

    fm = post.metadata
    body = post.content

    for required in ("title", "description", "slug", "date", "schemaType"):
        if not fm.get(required):
            issues.append(Issue("error", f"frontmatter.{required}", "Missing in frontmatter."))

    if fm.get("slug") and fm["slug"] != expected_slug:
        issues.append(
            Issue(
                "error",
                "frontmatter.slug",
                f"Expected {expected_slug!r}, found {fm['slug']!r}.",
            )
        )
    if fm.get("title") and fm["title"] != expected_headline:
        issues.append(
            Issue(
                "error",
                "frontmatter.title",
                f"Expected {expected_headline!r}, found {fm['title']!r}.",
            )
        )

    # Body heading hierarchy: exactly one H1 (rendered from headline),
    # at least one H2 if the strategist body was non-trivial.
    headings = [(m.group(1), m.start()) for m in _HEADING_RE.finditer(body)]
    h1s = [h for h in headings if len(h[0]) == 1]
    if len(h1s) != 1:
        issues.append(
            Issue(
                "error",
                "body.headings",
                f"Expected exactly 1 H1 (the headline), found {len(h1s)}.",
            )
        )
    elif h1s[0][1] != 0 and not body[: h1s[0][1]].strip() == "":
        # H1 should be the first non-blank line.
        issues.append(Issue("warning", "body.headings", "H1 is not the first heading in the body."))

    # No H4+ heading should appear (we cap at H3 for SEO clarity).
    deep = [h for h, _ in headings if len(h) >= 4]
    if deep:
        issues.append(
            Issue("warning", "body.headings", f"Found {len(deep)} H4+ heading(s); aim for H2/H3 only.")
        )

    # Image references in the body should map to assets we actually have.
    if available_image_paths is not None:
        for m in _MARKDOWN_IMAGE_RE.finditer(body):
            ref = m.group(1).split(" ", 1)[0]  # strip optional title
            if ref.startswith("http://") or ref.startswith("https://"):
                continue
            if ref not in available_image_paths:
                issues.append(
                    Issue(
                        "error",
                        "body.images",
                        f"Body references {ref!r} but no matching asset was provided.",
                    )
                )

    return issues


# --- Asset copying + write -------------------------------------------------


@dataclass
class RenderResult:
    ok: bool
    mdx_path: str
    assets_copied: list[str]
    issues: list[dict[str, str]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mdx_path": self.mdx_path,
            "assets_copied": self.assets_copied,
            "issues": self.issues,
        }


def _copy_assets(
    assets: list[dict[str, Any]],
    image_dir: Path,
) -> tuple[list[str], set[str]]:
    """Copy every asset that has a real `path` on disk into image_dir.

    Returns (copied_filesystem_paths, public_url_paths). Assets without a
    `path` (e.g., hero-description placeholders) are skipped silently.
    """
    image_dir.mkdir(parents=True, exist_ok=True)
    fs_paths: list[str] = []
    public_paths: set[str] = set()
    for asset in assets:
        src = asset.get("path")
        filename = asset.get("filename")
        if not src or not filename:
            continue
        src_path = Path(src)
        if not src_path.exists():
            continue
        dest = image_dir / filename
        shutil.copy2(src_path, dest)
        fs_paths.append(str(dest))
        public_paths.add(_public_image_path(filename, str(image_dir)))
    return fs_paths, public_paths


def render_article(
    draft: dict[str, Any],
    assets: list[dict[str, Any]],
    config: dict[str, Any],
    out_dir: str | Path | None = None,
    publish_date: str | None = None,
) -> RenderResult:
    """End-to-end: render MDX, copy assets, write the file, validate.

    Does NOT touch git — that's the agent's job, with care.
    """
    publishing = config.get("publishing") or {}
    nextjs = publishing.get("nextjs") or {}
    out_dir_path = Path(out_dir or publishing.get("output_dir") or "./content/blog")
    out_dir_path.mkdir(parents=True, exist_ok=True)

    image_dir_str = nextjs.get("image_dir") or "public/images/blog"
    image_dir = Path(image_dir_str)

    rendered = render_mdx(draft, assets, config, publish_date=publish_date)

    fs_paths, public_paths = _copy_assets(assets, image_dir)

    issues = validate_mdx(
        rendered,
        expected_slug=draft["slug"],
        expected_headline=draft["headline"],
        available_image_paths=public_paths,
    )

    mdx_path = out_dir_path / f"{draft['slug']}.mdx"
    mdx_path.write_text(rendered, encoding="utf-8")

    ok = not any(i.level == "error" for i in issues)
    return RenderResult(
        ok=ok,
        mdx_path=str(mdx_path),
        assets_copied=fs_paths,
        issues=[i.as_dict() for i in issues],
    )


# --- CLI -------------------------------------------------------------------


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_yaml(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _cmd_render(args: argparse.Namespace) -> int:
    draft = _load_json(args.draft)
    assets = _load_json(args.assets) if args.assets else []
    config = _load_yaml(args.config)
    if args.date:
        result = render_article(draft, assets, config, out_dir=args.out, publish_date=args.date)
    else:
        result = render_article(draft, assets, config, out_dir=args.out)
    json.dump(result.as_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="content_engine.publisher")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_render = sub.add_parser("render", help="Render a draft into MDX + assets.")
    p_render.add_argument("--draft", required=True, help="Path to strategist draft JSON.")
    p_render.add_argument("--assets", help="Path to asset-producer JSON. Optional.")
    p_render.add_argument("--config", required=True, help="Path to config YAML.")
    p_render.add_argument("--out", help="Override publishing.output_dir.")
    p_render.add_argument("--date", help="Override publish date (YYYY-MM-DD).")
    p_render.set_defaults(func=_cmd_render)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
