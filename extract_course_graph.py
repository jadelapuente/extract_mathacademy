#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _client import MathAcademyError
from _course_graph import build_curriculum_knowledge_graph_from_api


DEFAULT_COURSE_IDS = [113, 111, 136, 76]
DEFAULT_OUTPUT = Path("data/curriculum.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Math Academy course content and knowledge graphs into a "
            "local curriculum JSON."
        ),
    )
    parser.add_argument(
        "course_ids",
        nargs="*",
        type=int,
        default=DEFAULT_COURSE_IDS,
        help=(
            "Math Academy course IDs. Defaults to "
            f"{', '.join(str(course_id) for course_id in DEFAULT_COURSE_IDS)}."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output JSON path. Defaults to {DEFAULT_OUTPUT}.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    course_ids = list(args.course_ids or DEFAULT_COURSE_IDS)
    try:
        doc = build_curriculum_knowledge_graph_from_api(course_ids)
    except MathAcademyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    curriculum = doc["curriculum"]
    print(
        f"wrote {len(curriculum['course_ids'])} courses and "
        f"{len(curriculum['topic_ids'])} unique topics -> {output}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
