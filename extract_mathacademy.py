#!/usr/bin/env python3
"""
Extract questions, prose, and math notation from Math Academy lesson HTML,
stripping presentational markup and recovering LaTeX.

The output is optimized for LLM consumption: compact single-line LaTeX and a
stable structure (Markdown or JSON).

Patterns exploited
-------------------
1. Each lesson chunk is a  <div class="step" steptype="tutorial|example">.
     - Title:       div.stepName > a.stepAnchor   (examples prefix "Example:")
     - Question:    div.exampleQuestion           (examples only)
     - Explanation: div.exampleExplanation        (examples only)
     - Tutorials:   the <p> children of the step div
2. Every formula is a  <span class="mjpage">  (inline) or
   <span class="mjpage mjpage__block">  (display/block).
3. The math source lives in the SVG's <title>, NOT in the drawn paths:
     - MathJax v2 output -> <title> holds raw LaTeX as text.
     - MathJax v3 output -> <title> holds MathML (<math>...</math>); convert it.
4. Inline <style>/<script>, the "EXPLANATION" header and "?" buttons are noise.

Usage
-----
    python extract_mathacademy.py https://mathacademy.com/topics/285
    python extract_mathacademy.py https://mathacademy.com/topics/285 --format json
    python extract_mathacademy.py --start 2026-08-07 --end 2026-08-16
    python extract_mathacademy.py lesson.html        # local file also works
    cat lesson.html | python extract_mathacademy.py  # stdin too

When given a URL, the script reads your existing Math Academy login from your
browser's cookie store (no password needed -- just stay logged in in your
browser) and fetches the page. Math Academy renders math server-side, so a
plain HTTP fetch returns the same SVG the parser already understands.

Output is a self-contained per-lesson folder named after the lesson title:

    inverses-of-quadratic-functions/
        inverses-of-quadratic-functions.md
        <downloaded graphics>

Pass --out-dir to choose where that folder is created, or -o for an explicit
output file path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as dt_date
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

from _extract import clean, clean_inline, extract_steps, extract_title, node_text, slugify
from _mathml import conv_cell, mathml_to_latex, mjpage_to_latex, normalize_latex
from _render import to_json, to_markdown


# --------------------------------------------------------------------------- #
# Fetching (reuse the browser's existing Math Academy login)                  #
# --------------------------------------------------------------------------- #

MA_DOMAIN = "mathacademy.com"
MA_BASE_URL = f"https://{MA_DOMAIN}"


def _session_cookies():
    """Read the Math Academy `session` cookie from whichever local browser
    you're logged in with. Tries each in turn, skipping any that's locked or
    unreadable (e.g. Safari's permission-gated cookie store)."""
    import browser_cookie3 as bc3

    for name in ("chrome", "brave", "edge", "firefox", "safari"):
        try:
            cj = getattr(bc3, name)(domain_name=MA_DOMAIN)
        except Exception:                           # locked DB, no profile, etc.
            continue
        if any(c.name == "session" for c in cj):
            return cj
    raise SystemExit(
        "Could not find a Math Academy session in any browser. "
        "Log in at https://mathacademy.com, then run this again."
    )


def fetch_html(url: str, cookies=None) -> str:
    import requests

    r = requests.get(
        url,
        cookies=cookies if cookies is not None else _session_cookies(),
        headers={"User-Agent": "Mozilla/5.0"},
        allow_redirects=True,
        timeout=30,
    )
    # Bounced to a login/landing page => the session cookie is stale.
    if "/login" in r.url or 'type="password"' in r.text.lower():
        raise SystemExit(
            f"Got redirected to {r.url} -- your Math Academy session looks "
            "expired. Re-open mathacademy.com in your browser to refresh it."
        )
    r.raise_for_status()
    return r.text


def _iso_z(dt: datetime) -> str:
    """Render an aware datetime as the UTC ISO form Math Academy accepts."""
    return dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def _parse_completed_at(task: dict[str, Any]) -> datetime | None:
    completed = task.get("completed")
    if not completed:
        return None
    return datetime.fromisoformat(completed.replace("Z", "+00:00"))


def fetch_previous_tasks(before: datetime, cookies=None) -> list[dict[str, Any]]:
    """Fetch completed tasks older than `before`.

    This mirrors Math Academy's dashboard pagination endpoint. The server also
    accepts a misspelled `minumum` query parameter, but the default pagination
    was more reliable in live probing.
    """
    import requests

    url = f"{MA_BASE_URL}/api/previous-tasks/{quote(_iso_z(before), safe='')}"
    r = requests.get(
        url,
        cookies=cookies if cookies is not None else _session_cookies(),
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        allow_redirects=True,
        timeout=30,
    )
    if "/login" in r.url or 'type="password"' in r.text.lower():
        raise SystemExit(
            f"Got redirected to {r.url} -- your Math Academy session looks "
            "expired. Re-open mathacademy.com in your browser to refresh it."
        )
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as exc:
        raise SystemExit(
            "Math Academy did not return JSON for completed tasks. "
            "Your session may be expired."
        ) from exc
    if not isinstance(data, list):
        raise SystemExit("Unexpected Math Academy completed-task response.")
    return data


def completed_topic_ids(
    start_date: dt_date,
    end_date: dt_date,
    *,
    timezone: str = "America/Los_Angeles",
    cookies=None,
    include_review_topics: bool = False,
) -> list[int]:
    """Return unique topic ids completed within an inclusive local date range."""
    if end_date < start_date:
        raise ValueError("end date must be on or after start date")

    local_tz = ZoneInfo(timezone)
    utc = ZoneInfo("UTC")
    start_utc = datetime.combine(start_date, time.min, local_tz).astimezone(utc)
    end_exclusive_utc = datetime.combine(
        end_date + timedelta(days=1), time.min, local_tz
    ).astimezone(utc)

    allowed_types = {"Lesson"}
    if include_review_topics:
        allowed_types.add("Review")

    cookies = cookies if cookies is not None else _session_cookies()
    cursor = end_exclusive_utc
    seen_task_ids: set[int] = set()
    seen_topic_ids: dict[int, None] = {}

    while True:
        page = fetch_previous_tasks(cursor, cookies)
        if not page:
            break

        oldest_completed: datetime | None = None
        for task in page:
            completed_at = _parse_completed_at(task)
            if completed_at is None:
                continue
            oldest_completed = (
                completed_at
                if oldest_completed is None or completed_at < oldest_completed
                else oldest_completed
            )

            task_id = task.get("id")
            if isinstance(task_id, int):
                if task_id in seen_task_ids:
                    continue
                seen_task_ids.add(task_id)

            if not (start_utc <= completed_at < end_exclusive_utc):
                continue
            if task.get("type") not in allowed_types:
                continue

            topic = task.get("topic") or {}
            topic_id = topic.get("id")
            if isinstance(topic_id, int):
                seen_topic_ids.setdefault(topic_id, None)

        if oldest_completed is None or oldest_completed < start_utc:
            break
        if oldest_completed >= cursor:
            break
        cursor = oldest_completed

    return list(seen_topic_ids)


# Content-Type -> file extension for the image formats Math Academy serves.
_IMG_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


def _image_filename(src: str, content_type: str) -> str:
    """Local filename for an image src: keep its own extension if it has one,
    else append the one implied by the Content-Type (graphics srcs are
    extensionless hashes like /graphics/<hash>)."""
    p = Path(urlparse(src).path)
    if p.suffix:
        return p.name
    ext = _IMG_EXT.get(content_type.split(";")[0].strip(), ".img")
    return p.name + ext


def download_images(srcs, base_url: str, out_dir: Path, cookies) -> dict[str, str]:
    """Download each image src (resolved against base_url) into out_dir using
    the session cookie. Returns {original_src: local_filename}."""
    import requests

    mapping: dict[str, str] = {}
    for src in dict.fromkeys(srcs):                 # de-dup, keep order
        r = requests.get(
            urljoin(base_url, src),
            cookies=cookies,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        r.raise_for_status()
        fname = _image_filename(src, r.headers.get("content-type", ""))
        (out_dir / fname).write_bytes(r.content)
        mapping[src] = fname
    return mapping


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _url_stem(url: str) -> Path:
    """Derive an output filename stem from a URL, e.g. .../topics/285 -> 285."""
    name = Path(urlparse(url).path.rstrip("/")).name
    return Path(name or "lesson")


def write_extracted_lesson(
    html: str,
    *,
    fallback_name: str,
    fmt: str,
    out_dir: Path,
    output: Path | None = None,
    source_url: str | None = None,
    cookies=None,
    no_images: bool = False,
) -> tuple[Path, int]:
    steps = extract_steps(html)
    if not steps:
        print("warning: no lesson steps found in input", file=sys.stderr)

    title = extract_title(html)
    name = slugify(title) if title else fallback_name

    if fmt == "json":
        text, ext = to_json(steps), ".json"
    else:
        text, ext = to_markdown(steps, title), ".md"

    # Default layout: <out-dir>/<name>/<name>.<ext> with images alongside.
    out_path = output if output else out_dir / name / f"{name}{ext}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Download lesson images into the same directory and rewrite references.
    if source_url and not no_images:
        srcs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
        if srcs:
            mapping = download_images(srcs, source_url, out_path.parent, cookies)
            for src, fname in mapping.items():
                text = text.replace(f"]({src})", f"]({fname})")
            print(f"downloaded {len(mapping)} image(s) -> {out_path.parent}",
                  file=sys.stderr)

    out_path.write_text(text, encoding="utf-8")
    return out_path, len(steps)


def extract_completed_topics(
    start_date: dt_date,
    end_date: dt_date,
    *,
    timezone: str,
    out_dir: Path,
    fmt: str,
    no_images: bool,
    include_review_topics: bool,
) -> tuple[Path, list[int]]:
    if end_date < start_date:
        raise ValueError("end date must be on or after start date")

    cookies = _session_cookies()
    topic_ids = completed_topic_ids(
        start_date,
        end_date,
        timezone=timezone,
        cookies=cookies,
        include_review_topics=include_review_topics,
    )

    range_dir = out_dir / f"{start_date.isoformat()}-to-{end_date.isoformat()}"
    range_dir.mkdir(parents=True, exist_ok=True)
    (range_dir / "topic_ids.json").write_text(
        json.dumps(topic_ids, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest: list[dict[str, Any]] = []
    for index, topic_id in enumerate(topic_ids, start=1):
        url = f"{MA_BASE_URL}/topics/{topic_id}"
        html = fetch_html(url, cookies)
        out_path, step_count = write_extracted_lesson(
            html,
            fallback_name=str(topic_id),
            fmt=fmt,
            out_dir=range_dir,
            source_url=url,
            cookies=cookies,
            no_images=no_images,
        )
        manifest.append({
            "topic_id": topic_id,
            "url": url,
            "output": str(out_path),
            "steps": step_count,
        })
        print(
            f"[{index}/{len(topic_ids)}] wrote {step_count} steps -> {out_path}",
            file=sys.stderr,
        )

    (range_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return range_dir, topic_ids


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract Math Academy lesson content from HTML for LLM use.",
    )
    p.add_argument(
        "input", nargs="?",
        help="HTML file to read, or a mathacademy.com URL to fetch using your "
             "browser's existing login (omit to read from stdin).",
    )
    p.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="Output format (default: markdown).",
    )
    p.add_argument(
        "-o", "--output",
        help="Explicit output file path. Overrides the default per-lesson "
             "folder; images are written next to the output file.",
    )
    p.add_argument(
        "--out-dir", default=".",
        help="Root directory under which the per-lesson folder is created "
             "(default: current directory).",
    )
    p.add_argument(
        "--no-images", action="store_true",
        help="Don't download lesson images (URL input only).",
    )
    p.add_argument(
        "--start",
        type=dt_date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="Inclusive local start date for extracting completed lesson topics.",
    )
    p.add_argument(
        "--end",
        type=dt_date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="Inclusive local end date for extracting completed lesson topics.",
    )
    p.add_argument(
        "--timezone",
        default="America/Los_Angeles",
        help="IANA timezone used to interpret completed date bounds "
             "(default: America/Los_Angeles).",
    )
    p.add_argument(
        "--include-review-topics",
        action="store_true",
        help="Include completed Review task topic ids as well as Lesson topics.",
    )
    return p


def run(args: argparse.Namespace) -> int:
    if args.start or args.end:
        if not (args.start and args.end):
            print(
                "error: --start and --end must be used together",
                file=sys.stderr,
            )
            return 2
        if args.input:
            print(
                "error: completed-topic extraction does not accept an input "
                "URL/file",
                file=sys.stderr,
            )
            return 2
        if args.output:
            print(
                "error: use --out-dir for completed-topic extraction; -o is "
                "only for single lesson extraction",
                file=sys.stderr,
            )
            return 2
        try:
            range_dir, ids = extract_completed_topics(
                args.start,
                args.end,
                timezone=args.timezone,
                out_dir=Path(args.out_dir),
                fmt=args.format,
                no_images=args.no_images,
                include_review_topics=args.include_review_topics,
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        print(
            f"wrote {len(ids)} completed topic(s) -> {range_dir}",
            file=sys.stderr,
        )
        return 0

    source_url = None
    cookies = None
    if args.input and _is_url(args.input):
        source_url = args.input
        cookies = _session_cookies()
        html = fetch_html(source_url, cookies)
        fallback_name = str(_url_stem(source_url))
    elif args.input:
        in_path = Path(args.input)
        if not in_path.is_file():
            print(f"error: input file not found: {args.input}", file=sys.stderr)
            return 2
        html = in_path.read_text(encoding="utf-8")
        fallback_name = in_path.stem
    else:
        html = sys.stdin.read()
        fallback_name = "lesson"

    if not html.strip():
        print("error: empty input", file=sys.stderr)
        return 2

    out_path, step_count = write_extracted_lesson(
        html,
        fallback_name=fallback_name,
        fmt=args.format,
        out_dir=Path(args.out_dir),
        output=Path(args.output) if args.output else None,
        source_url=source_url,
        cookies=cookies,
        no_images=args.no_images,
    )
    print(f"wrote {step_count} steps -> {out_path}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
