from __future__ import annotations

import json

from extract_mathacademy.cli import assess_gaps as cli
from extract_mathacademy.pipeline.assess_gaps import (
    build_gap_groups,
    build_gap_inputs,
    build_missing_topics_report,
    groups_doc_from_topic_ids,
    prepare_mochi_decks,
)


def course_graph_fixture():
    return {
        "course": {
            "id": 113,
            "name": "Foundations",
            "section_ids": [100, 200],
            "subsection_ids": [10, 20],
            "topic_ids": [1, 2, 3, 4, 7, 8, 5, 6],
            "sections": [
                {
                    "id": 100,
                    "name": "Algebra",
                    "subsection_ids": [10],
                    "topic_ids": [1, 2, 3, 4, 7, 8],
                },
                {
                    "id": 200,
                    "name": "Geometry",
                    "subsection_ids": [20],
                    "topic_ids": [5, 6],
                },
            ],
            "subsections_by_id": {
                "10": {
                    "id": 10,
                    "section_id": 100,
                    "name": "Linear Equations",
                    "topic_ids": [1, 2, 3, 4, 7, 8],
                },
                "20": {
                    "id": 20,
                    "section_id": 200,
                    "name": "Conics",
                    "topic_ids": [5, 6],
                },
            },
        },
        "topics_by_id": {
            "1": {
                "id": 1,
                "name": "Solving Equations",
                "section_id": 100,
                "subsection_id": 10,
                "prev_id": None,
                "next_id": 2,
                "children": [3, 4],
                "parents": [99],
            },
            "2": {
                "id": 2,
                "name": "Graphing Lines",
                "section_id": 100,
                "subsection_id": 10,
                "prev_id": 1,
                "next_id": 5,
                "children": [3],
                "prerequisites": [1],
            },
            "3": {
                "id": 3,
                "name": "Equation Word Problems",
                "section_id": 100,
                "subsection_id": 10,
                "prev_id": 2,
                "next_id": 4,
                "children": [],
            },
            "4": {
                "id": 4,
                "name": "Systems",
                "section_id": 100,
                "subsection_id": 10,
                "prev_id": 3,
                "next_id": 7,
                "children": [],
            },
            "5": {
                "id": 5,
                "name": "Ellipses",
                "section_id": 200,
                "subsection_id": 20,
                "prev_id": 2,
                "next_id": 6,
                "children": [],
            },
            "6": {
                "id": 6,
                "name": "Hyperbolas",
                "section_id": 200,
                "subsection_id": 20,
                "prev_id": 5,
                "next_id": None,
                "children": [],
            },
            "7": {
                "id": 7,
                "name": "Parallel Lines",
                "section_id": 100,
                "subsection_id": 10,
                "prev_id": 4,
                "next_id": 5,
                "children": [],
            },
            "8": {
                "id": 8,
                "name": "Line Symmetry",
                "section_id": 100,
                "subsection_id": 10,
                "prev_id": None,
                "next_id": None,
                "children": [],
            },
        },
    }


def groups_fixture():
    return {
        "schema_version": 1,
        "groups": [
            {
                "slug": "linear-equations",
                "name": "Linear Equations",
                "topic_ids": [1, 2, 4, 999],
                "topics": [
                    {
                        "topic_id": 1,
                        "topic_name": "Solving Equations",
                        "prerequisite_topic_ids": [99],
                    }
                ],
            }
        ],
    }


def test_gap_groups_keep_targets_exactly_to_group_seed_topics():
    group = build_gap_groups(course_graph_fixture(), groups_fixture())[0]

    assert group["id"] == "linear-equations"
    assert [topic["id"] for topic in group["target_topics"]] == [1, 2, 4]
    assert "missing_topic_ids" not in group


def test_missing_topic_ids_are_separate_from_gap_groups():
    report = build_missing_topics_report(course_graph_fixture(), groups_fixture())

    assert report == {
        "total_missing_topic_ids": 1,
        "groups": [
            {
                "gap_group_id": "linear-equations",
                "gap_group_name": "Linear Equations",
                "missing_topic_ids": [999],
            }
        ],
    }


def test_missing_topics_report_is_none_when_no_topics_are_missing():
    groups_doc = {
        "schema_version": 1,
        "groups": [
            {
                "slug": "linear-equations",
                "name": "Linear Equations",
                "topic_ids": [1, 2, 4],
            }
        ],
    }

    assert build_missing_topics_report(course_graph_fixture(), groups_doc) is None


def test_gap_groups_keep_topic_summaries_minimal():
    topic = build_gap_groups(course_graph_fixture(), groups_fixture())[0][
        "target_topics"
    ][0]

    assert topic == {"id": 1, "name": "Solving Equations"}


def test_gap_context_topics_are_separate_from_targets():
    group = build_gap_groups(course_graph_fixture(), groups_fixture())[0]
    context_topics = group["context_topics"]

    assert context_topics[0] == {
        "id": 3,
        "name": "Equation Word Problems",
        "relations": [
            {"relation": "child", "source_topic_id": 1},
            {"relation": "child", "source_topic_id": 2},
            {"relation": "prev", "source_topic_id": 4},
        ],
    }
    assert {topic["id"]: topic["relations"] for topic in context_topics} == {
        3: [
            {"relation": "child", "source_topic_id": 1},
            {"relation": "child", "source_topic_id": 2},
            {"relation": "prev", "source_topic_id": 4},
        ],
    }
    assert not {topic["id"] for topic in group["target_topics"]} & {
        topic["id"] for topic in context_topics
    }


def test_gap_groups_do_not_include_parents_or_prerequisites():
    group = build_gap_groups(course_graph_fixture(), groups_fixture())[0]
    serialized = json.dumps(group)

    assert '"relation": "next"' not in serialized
    assert "parents" not in serialized
    assert "prerequisite" not in serialized


def test_gap_groups_include_next_context_only_when_opted_in():
    group = build_gap_groups(
        course_graph_fixture(),
        groups_fixture(),
        include_next_context=True,
    )[0]

    assert {topic["id"]: topic["relations"] for topic in group["context_topics"]} == {
        3: [
            {"relation": "child", "source_topic_id": 1},
            {"relation": "child", "source_topic_id": 2},
            {"relation": "prev", "source_topic_id": 4},
        ],
        5: [{"relation": "next", "source_topic_id": 2}],
        7: [{"relation": "next", "source_topic_id": 4}],
    }


def test_context_topic_keeps_multiple_relations_to_targets():
    group = build_gap_groups(course_graph_fixture(), groups_fixture())[0]
    equation_word_problems = next(
        topic for topic in group["context_topics"] if topic["id"] == 3
    )

    assert equation_word_problems["relations"] == [
        {"relation": "child", "source_topic_id": 1},
        {"relation": "child", "source_topic_id": 2},
        {"relation": "prev", "source_topic_id": 4},
    ]


def fake_mochi_decks():
    return {
        "docs": [
            {"id": "math", "sort": 3, "name": "Math", "parent-id": None},
            {"id": "other", "sort": 1, "name": "Programming", "parent-id": None},
            {"id": "alg", "sort": 1, "name": "Algebra", "parent-id": "math"},
            {"id": "calc", "sort": 2, "name": "Calculus", "parent-id": "math"},
            {"id": "lin", "sort": 1, "name": "Linear Equations", "parent-id": "alg"},
            {"id": "py", "sort": 1, "name": "Python", "parent-id": "other"},
        ]
    }


def test_prepare_mochi_decks_finds_root_by_name_and_collects_descendants():
    decks = prepare_mochi_decks(fake_mochi_decks())

    assert [deck["id"] for deck in decks] == ["math", "alg", "lin", "calc"]
    assert [deck["name"] for deck in decks] == [
        "Math",
        "Math / Algebra",
        "Math / Algebra / Linear Equations",
        "Math / Calculus",
    ]
    assert set(decks[0]) == {"id", "name"}


def test_prepare_mochi_decks_finds_root_by_id_and_excludes_non_math_decks():
    decks = prepare_mochi_decks(
        fake_mochi_decks(),
        root_deck_id="other",
        root_deck_name="Ignored",
    )

    assert [deck["id"] for deck in decks] == ["other", "py"]
    assert decks[1]["name"] == "Programming / Python"


def test_build_gap_inputs_does_not_require_or_emit_card_content():
    doc = build_gap_inputs(course_graph_fixture(), groups_fixture(), fake_mochi_decks())
    serialized = json.dumps(doc)

    assert set(doc) == {"gap_groups", "all_math_decks"}
    assert doc["all_math_decks"] == [
        {
            "id": "math",
            "name": "Math",
        },
        {
            "id": "alg",
            "name": "Math / Algebra",
        },
        {
            "id": "lin",
            "name": "Math / Algebra / Linear Equations",
        },
        {
            "id": "calc",
            "name": "Math / Calculus",
        },
    ]
    assert "content" not in serialized
    assert "card" not in serialized.casefold()
    assert "placements" not in serialized
    assert "missing_topic_ids" not in serialized


def test_cli_writes_missing_topics_report_only_when_topics_are_missing(tmp_path):
    curriculum_path = tmp_path / "curriculum.json"
    groups_path = tmp_path / "groups.json"
    decks_path = tmp_path / "mochi-decks.json"
    output_path = tmp_path / "mochi-gap-inputs.json"
    missing_topics_path = tmp_path / "mochi-gap-missing-topics.json"

    curriculum_path.write_text(json.dumps(course_graph_fixture()), encoding="utf-8")
    groups_path.write_text(json.dumps(groups_fixture()), encoding="utf-8")
    decks_path.write_text(json.dumps(fake_mochi_decks()), encoding="utf-8")

    rc = cli.main(
        [
            "--curriculum",
            str(curriculum_path),
            "--groups",
            str(groups_path),
            "--mochi-decks-json",
            str(decks_path),
            "--output",
            str(output_path),
            "--missing-topics-output",
            str(missing_topics_path),
        ]
    )

    assert rc == 0
    assert "missing_topic_ids" not in output_path.read_text(encoding="utf-8")
    assert json.loads(missing_topics_path.read_text(encoding="utf-8")) == {
        "total_missing_topic_ids": 1,
        "groups": [
            {
                "gap_group_id": "linear-equations",
                "gap_group_name": "Linear Equations",
                "missing_topic_ids": [999],
            }
        ],
    }

    groups_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "groups": [
                    {
                        "slug": "linear-equations",
                        "name": "Linear Equations",
                        "topic_ids": [1, 2, 4],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rc = cli.main(
        [
            "--curriculum",
            str(curriculum_path),
            "--groups",
            str(groups_path),
            "--mochi-decks-json",
            str(decks_path),
            "--output",
            str(output_path),
            "--missing-topics-output",
            str(missing_topics_path),
        ]
    )

    assert rc == 0
    assert not missing_topics_path.exists()


def test_cli_missing_topics_output_defaults_to_data_path():
    parser = cli._build_parser()
    args = parser.parse_args(["--groups", "groups.json"])

    assert args.missing_topics_output == "data/mochi-gap-missing-topics.json"


def test_single_topic_input_uses_same_gap_group_shape():
    groups_doc = groups_doc_from_topic_ids([2], course_graph_fixture())
    doc = build_gap_inputs(course_graph_fixture(), groups_doc, fake_mochi_decks())

    assert groups_doc["groups"] == [
        {
            "slug": "topic-2",
            "name": "Graphing Lines",
            "topic_ids": [2],
        }
    ]
    assert doc["gap_groups"][0]["id"] == "topic-2"
    assert [topic["id"] for topic in doc["gap_groups"][0]["target_topics"]] == [2]
