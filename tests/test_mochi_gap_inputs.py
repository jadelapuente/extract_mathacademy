from __future__ import annotations

import json

from _mochi_gap_inputs import (
    build_gap_groups,
    build_gap_inputs,
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
                "children": [],
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
    assert group["missing_topic_ids"] == [999]


def test_gap_groups_find_section_and_subsection_names_in_placements():
    topic = build_gap_groups(course_graph_fixture(), groups_fixture())[0][
        "target_topics"
    ][0]

    assert topic["placements"] == [
        {
            "course_id": 113,
            "course_name": "Foundations",
            "section_id": 100,
            "section_name": "Algebra",
            "subsection_id": 10,
            "subsection_name": "Linear Equations",
        }
    ]


def test_gap_context_topics_are_separate_from_targets():
    group = build_gap_groups(course_graph_fixture(), groups_fixture())[0]
    context_topics = group["context_topics"]

    assert context_topics[0] == {
        "id": 3,
        "name": "Equation Word Problems",
        "placements": [
            {
                "course_id": 113,
                "course_name": "Foundations",
                "section_id": 100,
                "section_name": "Algebra",
                "subsection_id": 10,
                "subsection_name": "Linear Equations",
            }
        ],
        "relation": "child",
        "source_topic_id": 1,
    }
    assert {topic["id"]: topic["relation"] for topic in context_topics} == {
        3: "child",
        5: "next",
        7: "next",
    }
    assert not {topic["id"] for topic in group["target_topics"]} & {
        topic["id"] for topic in context_topics
    }


def test_gap_groups_do_not_include_same_subsection_or_parents_by_default():
    group = build_gap_groups(course_graph_fixture(), groups_fixture())[0]
    serialized = json.dumps(group)

    assert "same_subsection" not in serialized
    assert "parents" not in serialized
    assert "prerequisite" not in serialized


def test_gap_groups_include_same_subsection_context_only_when_opted_in():
    group = build_gap_groups(
        course_graph_fixture(),
        groups_fixture(),
        include_same_subsection_context=True,
    )[0]
    same_subsection = [
        topic for topic in group["context_topics"] if topic["relation"] == "same_subsection"
    ]

    assert same_subsection == [
        {
            "id": 8,
            "name": "Line Symmetry",
            "placements": [
                {
                    "course_id": 113,
                    "course_name": "Foundations",
                    "section_id": 100,
                    "section_name": "Algebra",
                    "subsection_id": 10,
                    "subsection_name": "Linear Equations",
                }
            ],
            "relation": "same_subsection",
            "source_topic_id": None,
        }
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
    assert [deck["path"] for deck in decks] == [
        "Math",
        "Math / Algebra",
        "Math / Algebra / Linear Equations",
        "Math / Calculus",
    ]
    assert set(decks[0]) == {"id", "name", "parent_id", "path"}


def test_prepare_mochi_decks_finds_root_by_id_and_excludes_non_math_decks():
    decks = prepare_mochi_decks(
        fake_mochi_decks(),
        root_deck_id="other",
        root_deck_name="Ignored",
    )

    assert [deck["id"] for deck in decks] == ["other", "py"]
    assert decks[1]["path"] == "Programming / Python"


def test_build_gap_inputs_does_not_require_or_emit_card_content():
    doc = build_gap_inputs(course_graph_fixture(), groups_fixture(), fake_mochi_decks())
    serialized = json.dumps(doc)

    assert set(doc) == {"gap_groups", "mochi_decks", "llm_deck_judging_units"}
    assert doc["llm_deck_judging_units"] == [
        {
            "gap_group_id": "linear-equations",
            "candidate_deck_ids": ["math", "alg", "lin", "calc"],
        }
    ]
    assert "content" not in serialized
    assert "card" not in serialized.casefold()


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
    assert doc["llm_deck_judging_units"][0]["gap_group_id"] == "topic-2"
