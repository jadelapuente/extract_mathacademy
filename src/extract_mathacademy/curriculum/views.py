from __future__ import annotations

from typing import Any


def curriculum_view(course_graph: dict[str, Any]) -> dict[str, Any]:
    if "course" in course_graph:
        course = course_graph["course"]
        return {
            "primary_course": course,
            "courses_by_id": {str(course["id"]): course},
            "course_ids": [course["id"]],
            "section_ids": course.get("section_ids", []),
            "subsection_ids": course.get("subsection_ids", []),
            "section_by_id": {
                str(section["id"]): section for section in course.get("sections", [])
            },
            "subsections_by_id": course.get("subsections_by_id", {}),
        }

    curriculum = course_graph["curriculum"]
    courses_by_id = course_graph["courses_by_id"]
    section_ids: list[Any] = []
    subsection_ids: list[Any] = []
    section_by_id: dict[str, dict[str, Any]] = {}
    subsections_by_id: dict[str, dict[str, Any]] = {}

    for course_id in curriculum.get("course_ids", []):
        course = courses_by_id[str(course_id)]
        section_ids.extend(course.get("section_ids", []))
        subsection_ids.extend(course.get("subsection_ids", []))
        for section in course.get("sections", []):
            section_by_id[str(section["id"])] = section
        subsections_by_id.update(course.get("subsections_by_id", {}))

    return {
        "primary_course": {"id": None, "name": "Curriculum"},
        "courses_by_id": courses_by_id,
        "course_ids": curriculum.get("course_ids", []),
        "section_ids": dedupe_preserve_order(section_ids),
        "subsection_ids": dedupe_preserve_order(subsection_ids),
        "section_by_id": section_by_id,
        "subsections_by_id": subsections_by_id,
    }


def topic_summary(
    topic: dict[str, Any],
    curriculum: dict[str, Any],
    *,
    relation: str | None = None,
    source_topic_id: Any = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": topic.get("id"),
        "name": topic.get("name"),
    }
    if relation is not None:
        summary["relation"] = relation
        summary["source_topic_id"] = source_topic_id
    return summary


def dedupe_preserve_order(values: Any) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if value is None or key in seen:
            continue
        output.append(value)
        seen.add(key)
    return output

