from __future__ import annotations

import argparse
import json

from extract_mathacademy.cli import extract_course_graph as cli
from extract_mathacademy.mathacademy.course_graph import build_course_knowledge_graph, build_curriculum_knowledge_graph


def sample_content():
    return {
        "result": True,
        "units": [
            {
                "id": 709,
                "name": "Fractions",
                "number": 1,
                "numeral": "I",
                "modules": [
                    {
                        "id": 121714,
                        "name": (
                            "Adding and Subtracting Fractions and Whole Numbers"
                        ),
                        "number": 1,
                        "topics": [
                            {
                                "id": 543,
                                "name": (
                                    "Adding Fractions and Whole Numbers "
                                    "Using Models"
                                ),
                                "live": 1,
                                "optional": 0,
                                "number": 1,
                                "url": (
                                    "adding-fractions-and-whole-numbers-"
                                    "using-models"
                                ),
                            },
                            {
                                "id": 539,
                                "name": "Adding Fractions and Whole Numbers",
                                "live": 1,
                                "optional": 0,
                                "number": 2,
                                "url": "adding-fractions-and-whole-numbers",
                            },
                            {
                                "id": 544,
                                "name": (
                                    "Subtracting Fractions and Whole Numbers "
                                    "Using Models"
                                ),
                                "live": 1,
                                "optional": 0,
                                "number": 3,
                                "url": (
                                    "subtracting-fractions-and-whole-numbers-"
                                    "using-models"
                                ),
                            },
                            {
                                "id": 545,
                                "name": (
                                    "Subtracting Fractions and Whole Numbers"
                                ),
                                "live": 1,
                                "optional": 0,
                                "number": 4,
                                "url": (
                                    "subtracting-fractions-and-whole-numbers"
                                ),
                            },
                        ],
                    }
                ],
            }
        ],
    }


def sample_knowledge_graph():
    return {
        "result": True,
        "topics": {
            "543": {
                "id": 543,
                "name": "Adding Fractions and Whole Numbers Using Models",
                "course": {"id": 113, "name": "Mathematical Foundations I"},
                "prerequisites": [],
            },
            "539": {
                "id": 539,
                "name": "Adding Fractions and Whole Numbers",
                "course": {"id": 113, "name": "Mathematical Foundations I"},
                "prerequisites": [543],
            },
            "544": {
                "id": 544,
                "name": "Subtracting Fractions and Whole Numbers Using Models",
                "course": {"id": 113, "name": "Mathematical Foundations I"},
                "prerequisites": [543],
            },
            "545": {
                "id": 545,
                "name": "Subtracting Fractions and Whole Numbers",
                "course": {"id": 113, "name": "Mathematical Foundations I"},
                "prerequisites": [539, 544, 9999],
            },
            "9999": {
                "id": 9999,
                "name": "Outside Course Topic",
                "course": {"id": 999, "name": "Other Course"},
                "prerequisites": [545],
            },
        },
    }


def test_build_course_knowledge_graph_returns_course_and_topics_dictionaries():
    doc = build_course_knowledge_graph(
        113,
        content=sample_content(),
        knowledge_graph=sample_knowledge_graph(),
    )

    assert set(doc) == {"course", "topics_by_id"}
    assert doc["course"]["id"] == 113
    assert doc["course"]["name"] == "Mathematical Foundations I"
    assert doc["course"]["section_ids"] == [709]
    assert doc["course"]["subsection_ids"] == [121714]
    assert doc["course"]["topic_ids"] == [543, 539, 544, 545]

    section = doc["course"]["sections"][0]
    assert section["id"] == 709
    assert section["subsection_ids"] == [121714]
    assert section["topic_ids"] == [543, 539, 544, 545]

    subsection = doc["course"]["subsections_by_id"]["121714"]
    assert subsection == {
        "id": 121714,
        "section_id": 709,
        "number": 1,
        "name": "Adding and Subtracting Fractions and Whole Numbers",
        "topic_ids": [543, 539, 544, 545],
    }


def test_topics_by_id_contains_graph_edges_and_fast_placement_lookup():
    topics = build_course_knowledge_graph(
        113,
        content=sample_content(),
        knowledge_graph=sample_knowledge_graph(),
    )["topics_by_id"]

    topic = topics["545"]
    assert topic["name"] == "Subtracting Fractions and Whole Numbers"
    assert topic["children"] == []
    assert "parents" not in topic
    assert topic["prev_id"] == 544
    assert topic["next_id"] is None
    assert topic["prev_in_subsection_id"] == 544
    assert topic["next_in_subsection_id"] is None
    assert topic["course_id"] == 113
    assert topic["section_id"] == 709
    assert topic["subsection_id"] == 121714

    assert "9999" not in topics
    assert topics["543"]["children"] == [539, 544]


def test_course_graph_cli_writes_json(monkeypatch, tmp_path):
    out = tmp_path / "curriculum.json"
    doc = build_course_knowledge_graph(
        113,
        content=sample_content(),
        knowledge_graph=sample_knowledge_graph(),
    )
    curriculum = build_curriculum_knowledge_graph([doc])
    monkeypatch.setattr(
        cli,
        "build_curriculum_knowledge_graph_from_api",
        lambda course_ids: curriculum,
    )

    rc = cli.run(argparse.Namespace(course_ids=[113], output=str(out)))

    assert rc == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written) == {"curriculum", "courses_by_id", "topics_by_id"}
    assert written["curriculum"]["course_ids"] == [113]
    assert written["curriculum"]["topic_ids"] == [543, 539, 544, 545]
    assert "parents" not in written["topics_by_id"]["545"]


def test_course_graph_cli_default_course_ids_include_full_curriculum():
    parser = cli._build_parser()
    args = parser.parse_args([])

    assert args.course_ids == [113, 111, 136, 76, 43, 105, 106]
    assert args.output == "data/curriculum.json"


def test_build_curriculum_knowledge_graph_merges_courses_and_topics():
    first = build_course_knowledge_graph(
        113,
        content=sample_content(),
        knowledge_graph=sample_knowledge_graph(),
    )
    second_content = sample_content()
    second_content["units"][0]["id"] = 800
    second_content["units"][0]["name"] = "Repeated Fractions"
    second_content["units"][0]["modules"][0]["id"] = 900
    second = build_course_knowledge_graph(
        111,
        content=second_content,
        knowledge_graph=sample_knowledge_graph(),
    )

    curriculum = build_curriculum_knowledge_graph([first, second])

    assert curriculum["curriculum"]["course_ids"] == [113, 111]
    assert curriculum["curriculum"]["topic_ids"] == [543, 539, 544, 545]
    assert set(curriculum["courses_by_id"]) == {"113", "111"}
    topic = curriculum["topics_by_id"]["543"]
    assert topic["course_ids"] == [113, 111]
    assert topic["placements"] == [
        {"course_id": 113, "section_id": 709, "subsection_id": 121714},
        {"course_id": 111, "section_id": 800, "subsection_id": 900},
    ]
