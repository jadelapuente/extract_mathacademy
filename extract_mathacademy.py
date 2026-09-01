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
import sys
from datetime import date as dt_date
from pathlib import Path
from urllib.parse import urlparse

from _client import (
    MA_BASE_URL,
    MA_DOMAIN,
    MathAcademyClient,
    fetch_html,
    fetch_previous_tasks,
    session_cookies as _session_cookies,
)
from _completed import completed_topic_ids as _completed_topic_ids
from _completed import completed_topic_records as _completed_topic_records
from _completed import extract_completed_topics as _extract_completed_topics
from _completed import parse_completed_at as _parse_completed_at
from _extract import clean, clean_inline, extract_prerequisite_topic_ids
from _extract import extract_steps, extract_title, node_text, slugify
from _mathml import conv_cell, mathml_to_latex, mjpage_to_latex, normalize_latex
from _render import to_json, to_markdown
from _writer import download_images, image_filename as _image_filename
from _writer import write_extracted_lesson as _write_extracted_lesson


def completed_topic_ids(
    start_date: dt_date,
    end_date: dt_date,
    *,
    timezone: str = "America/Los_Angeles",
    cookies=None,
    include_review_topics: bool = False,
) -> list[int]:
    return _completed_topic_ids(
        start_date,
        end_date,
        timezone=timezone,
        cookies=cookies,
        include_review_topics=include_review_topics,
        fetch_previous_tasks_fn=fetch_previous_tasks,
        session_cookies_fn=_session_cookies,
    )


def completed_topic_records(
    start_date: dt_date,
    end_date: dt_date,
    *,
    timezone: str = "America/Los_Angeles",
    cookies=None,
    include_review_topics: bool = False,
):
    return _completed_topic_records(
        start_date,
        end_date,
        timezone=timezone,
        cookies=cookies,
        include_review_topics=include_review_topics,
        fetch_previous_tasks_fn=fetch_previous_tasks,
        session_cookies_fn=_session_cookies,
    )


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
    return _write_extracted_lesson(
        html,
        fallback_name=fallback_name,
        fmt=fmt,
        out_dir=out_dir,
        output=output,
        source_url=source_url,
        cookies=cookies,
        no_images=no_images,
        download_images_fn=download_images,
        stderr=sys.stderr,
    )


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
    return _extract_completed_topics(
        start_date,
        end_date,
        timezone=timezone,
        out_dir=out_dir,
        fmt=fmt,
        no_images=no_images,
        include_review_topics=include_review_topics,
        session_cookies_fn=_session_cookies,
        completed_topic_records_fn=completed_topic_records,
        fetch_html_fn=fetch_html,
        write_extracted_lesson_fn=write_extracted_lesson,
        base_url=MA_BASE_URL,
        stderr=sys.stderr,
    )


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
