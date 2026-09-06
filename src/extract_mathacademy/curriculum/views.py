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


def placement_summaries(
    topic: dict[str, Any],
    curriculum: dict[str, Any],
) -> list[dict[str, Any]]:
    courses_by_id = curriculum["courses_by_id"]
    section_by_id = curriculum["section_by_id"]
    subsections_by_id = curriculum["subsections_by_id"]
    placements = topic.get("placements") or [
        {
            "course_id": topic.get("course_id") or _single_course_id(curriculum),
            "section_id": topic.get("section_id"),
            "subsection_id": topic.get("subsection_id"),
        }
    ]
    return [
        {
            "course_id": placement.get("course_id"),
            "course_name": _name_by_id(courses_by_id, placement.get("course_id")),
            "section_id": placement.get("section_id"),
            "section_name": _name_by_id(section_by_id, placement.get("section_id")),
            "subsection_id": placement.get("subsection_id"),
            "subsection_name": _name_by_id(
                subsections_by_id,
                placement.get("subsection_id"),
            ),
        }
        for placement in placements
    ]


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


def _name_by_id(items_by_id: dict[str, dict[str, Any]], item_id: Any) -> str | None:
    item = items_by_id.get(str(item_id))
    name = item.get("name") if item else None
    return name if isinstance(name, str) else None


def _single_course_id(curriculum: dict[str, Any]) -> Any:
    course_ids = curriculum["course_ids"]
    return course_ids[0] if len(course_ids) == 1 else None
