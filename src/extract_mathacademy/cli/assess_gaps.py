#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extract_mathacademy.io.json_files import load_json, write_json
from extract_mathacademy.pipeline.assess_gaps import (
    build_gap_inputs,
    groups_doc_from_topic_ids,
)


DEFAULT_CURRICULUM_JSON = Path("data/curriculum.json")
DEFAULT_MOCHI_DECKS_JSON = Path("data/mochi-decks.json")
DEFAULT_OUTPUT = Path("data/mochi-gap-inputs.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build Math Academy gap groups and Mochi deck candidates for later "
            "LLM relevance judging."
        ),
    )
    parser.add_argument(
        "--curriculum",
        default=str(DEFAULT_CURRICULUM_JSON),
        help=f"Curriculum JSON path. Defaults to {DEFAULT_CURRICULUM_JSON}.",
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--groups", help="Extracted groups.json path.")
    inputs.add_argument(
        "--topic-id",
        action="append",
        type=int,
        dest="topic_ids",
        help=(
            "Single Math Academy topic ID to analyze. May be repeated. "
            "Creates one compatible one-topic gap group per ID."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output gap-inputs JSON path. Defaults to {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--mochi-decks-json",
        default=None,
        help=(
            "JSON file containing a Mochi list_decks response or docs array. "
            f"Defaults to {DEFAULT_MOCHI_DECKS_JSON} when that file exists."
        ),
    )
    parser.add_argument(
        "--mochi-root-deck-id",
        default=None,
        help="Optional Mochi root deck ID. Overrides --mochi-root-deck-name.",
    )
    parser.add_argument(
        "--mochi-root-deck-name",
        default="Math",
        help='Mochi root deck name to find when no ID is provided. Defaults to "Math".',
    )
    parser.add_argument(
        "--include-same-subsection-context",
        action="store_true",
        help=(
            "Opt in to same-subsection topic context. These topics are always "
            "included as context topics, never target topics."
        ),
    )
    return parser


def run(args: argparse.Namespace) -> int:
    curriculum = load_json(args.curriculum)
    groups_doc = (
        load_json(args.groups)
        if args.groups
        else groups_doc_from_topic_ids(args.topic_ids, curriculum)
    )
    decks_path = _resolve_decks_path(args.mochi_decks_json)
    if decks_path is None:
        print(
            "error: Mochi deck metadata is required. Fetch it with the Mochi "
            "list_decks tool and save it as data/mochi-decks.json, or pass "
            "--mochi-decks-json.",
            file=sys.stderr,
        )
        return 2

    try:
        doc = build_gap_inputs(
            curriculum,
            groups_doc,
            load_json(decks_path),
            mochi_root_deck_id=args.mochi_root_deck_id,
            mochi_root_deck_name=args.mochi_root_deck_name,
            include_same_subsection_context=args.include_same_subsection_context,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    write_json(args.output, doc)
    print(
        f"wrote {len(doc['gap_groups'])} gap groups and "
        f"{len(doc['all_math_decks'])} Mochi deck candidates -> {args.output}",
        file=sys.stderr,
    )
    return 0


def _resolve_decks_path(path: str | None) -> Path | None:
    if path:
        return Path(path)
    if DEFAULT_MOCHI_DECKS_JSON.exists():
        return DEFAULT_MOCHI_DECKS_JSON
    return None


def main(argv: list[str] | None = None) -> int:
    return run(_build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
