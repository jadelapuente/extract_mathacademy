from __future__ import annotations

from copy import deepcopy
from collections import defaultdict
from typing import Any

from extract_mathacademy.mathacademy.client import InvalidResponseError, MathAcademyClient


def fetch_course_content(
    course_id: int,
    *,
    client: MathAcademyClient | None = None,
) -> dict[str, Any]:
    client = client or MathAcademyClient()
    data = client.fetch_json(f"/api/courses/{course_id}/content")
    if not isinstance(data, dict) or data.get("result") is not True:
        raise InvalidResponseError("Unexpected Math Academy course-content response.")
    units = data.get("units")
    if not isinstance(units, list):
        raise InvalidResponseError("Course-content response did not include units.")
    return data


def fetch_course_knowledge_graph(
    course_id: int,
    *,
    client: MathAcademyClient | None = None,
) -> dict[str, Any]:
    client = client or MathAcademyClient()
    data = client.fetch_json(f"/api/courses/{course_id}/knowledge-graph")
    if not isinstance(data, dict) or data.get("result") is not True:
        raise InvalidResponseError(
            "Unexpected Math Academy course-knowledge-graph response."
        )
    topics = data.get("topics")
    if not isinstance(topics, dict):
        raise InvalidResponseError(
            "Course-knowledge-graph response did not include topics."
        )
    return data


def build_course_knowledge_graph(
    course_id: int,
    *,
    content: dict[str, Any],
    knowledge_graph: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build local course and topic dictionaries for a Math Academy course."""
    raw_graph_topics = knowledge_graph.get("topics", {})
    graph_topics = {
        _int_key(topic_id): topic
        for topic_id, topic in raw_graph_topics.items()
        if _int_key(topic_id) is not None and isinstance(topic, dict)
    }

    course_name = _course_name(course_id, content, graph_topics)
    course = {
        "id": course_id,
        "name": course_name,
        "section_ids": [],
        "subsection_ids": [],
        "topic_ids": [],
        "sections": [],
        "subsections_by_id": {},
    }

    topics_by_id: dict[str, dict[str, Any]] = {}
    placements_by_topic_id: dict[int, list[dict[str, Any]]] = defaultdict(list)

    ordered_course_topic_ids: list[int] = []
    for unit in content.get("units", []):
        if not isinstance(unit, dict):
            continue
        unit_id = _expect_int(unit.get("id"), "unit id")
        unit_number = _expect_int(unit.get("number"), "unit number")
        unit_doc = {
            "id": unit_id,
            "number": unit_number,
            "numeral": unit.get("numeral") or unit.get("romanNumeral"),
            "name": str(unit.get("name") or ""),
            "subsection_ids": [],
            "topic_ids": [],
        }
        course["section_ids"].append(unit_id)

        for module in unit.get("modules", []):
            if not isinstance(module, dict):
                continue
            module_id = _expect_int(module.get("id"), "module id")
            module_number = _expect_int(module.get("number"), "module number")
            module_doc = {
                "id": module_id,
                "section_id": unit_id,
                "number": module_number,
                "name": str(module.get("name") or ""),
                "topic_ids": [],
            }
            unit_doc["subsection_ids"].append(module_id)
            course["subsection_ids"].append(module_id)

            module_topic_ids: list[int] = []
            for raw_topic in module.get("topics", []):
                if not isinstance(raw_topic, dict):
                    continue
                topic_id = _expect_int(raw_topic.get("id"), "topic id")
                module_topic_ids.append(topic_id)
                ordered_course_topic_ids.append(topic_id)

                placement = {
                    "course_id": course_id,
                    "section_id": unit_id,
                    "subsection_id": module_id,
                }
                placements_by_topic_id[topic_id].append(placement)

                graph_topic = graph_topics.get(topic_id, {})
                topic_name = str(
                    graph_topic.get("name") or raw_topic.get("name") or ""
                )
                topic_doc = _topic_doc(
                    topic_id,
                    name=topic_name,
                    course_id=course_id,
                )
                topics_by_id[str(topic_id)] = topic_doc

                module_doc["topic_ids"].append(topic_id)

            _add_module_neighbors(module_doc["topic_ids"], topics_by_id)

            unit_doc["topic_ids"].extend(module_topic_ids)
            course["subsections_by_id"][str(module_id)] = module_doc

        course["sections"].append(unit_doc)

    course["topic_ids"] = ordered_course_topic_ids

    _add_course_neighbors(ordered_course_topic_ids, topics_by_id)
    _merge_graph_topics(
        topics_by_id,
        graph_topics,
        course_id=course_id,
        course_topic_ids=set(ordered_course_topic_ids),
    )
    _add_placements(topics_by_id, placements_by_topic_id)
    _add_dependent_edges(topics_by_id)

    return {"course": course, "topics_by_id": topics_by_id}


def build_course_knowledge_graph_from_api(
    course_id: int,
    *,
    client: MathAcademyClient | None = None,
) -> dict[str, dict[str, Any]]:
    client = client or MathAcademyClient()
    content = fetch_course_content(course_id, client=client)
    knowledge_graph = fetch_course_knowledge_graph(course_id, client=client)
    return build_course_knowledge_graph(
        course_id,
        content=content,
        knowledge_graph=knowledge_graph,
    )


def build_curriculum_knowledge_graph(
    course_graphs: list[dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Merge multiple course graphs into one curriculum lookup document."""
    courses_by_id: dict[str, dict[str, Any]] = {}
    topic_ids: list[int] = []
    seen_topic_ids: set[int] = set()
    topics_by_id: dict[str, dict[str, Any]] = {}

    for course_graph in course_graphs:
        course = deepcopy(course_graph["course"])
        course_id = course["id"]
        courses_by_id[str(course_id)] = course

        for topic_id in course.get("topic_ids", []):
            if topic_id not in seen_topic_ids:
                topic_ids.append(topic_id)
                seen_topic_ids.add(topic_id)

        for topic_key, topic in course_graph["topics_by_id"].items():
            merged = topics_by_id.get(topic_key)
            if merged is None:
                merged = deepcopy(topic)
                merged["course_ids"] = [course_id]
                merged["placements"] = [_topic_placement(topic)]
                topics_by_id[topic_key] = merged
                continue

            if not merged.get("name") and topic.get("name"):
                merged["name"] = topic["name"]
            if course_id not in merged["course_ids"]:
                merged["course_ids"].append(course_id)
            placement = _topic_placement(topic)
            if placement not in merged["placements"]:
                merged["placements"].append(placement)
            merged["children"] = sorted(
                set(merged.get("children", [])) | set(topic.get("children", []))
            )

    courses = [courses_by_id[str(graph["course"]["id"])] for graph in course_graphs]
    return {
        "curriculum": {
            "course_ids": [course["id"] for course in courses],
            "courses": [
                {
                    "id": course["id"],
                    "name": course.get("name"),
                    "section_count": len(course.get("section_ids", [])),
                    "subsection_count": len(course.get("subsection_ids", [])),
                    "topic_count": len(course.get("topic_ids", [])),
                }
                for course in courses
            ],
            "topic_ids": topic_ids,
        },
        "courses_by_id": courses_by_id,
        "topics_by_id": topics_by_id,
    }


def build_curriculum_knowledge_graph_from_api(
    course_ids: list[int],
    *,
    client: MathAcademyClient | None = None,
) -> dict[str, Any]:
    client = client or MathAcademyClient()
    return build_curriculum_knowledge_graph(
        [
            build_course_knowledge_graph_from_api(course_id, client=client)
            for course_id in course_ids
        ]
    )


def _topic_placement(topic: dict[str, Any]) -> dict[str, Any]:
    return {
        "course_id": topic.get("course_id"),
        "section_id": topic.get("section_id"),
        "subsection_id": topic.get("subsection_id"),
    }


def _topic_doc(
    topic_id: int,
    *,
    name: str,
    course_id: int,
) -> dict[str, Any]:
    return {
        "id": topic_id,
        "name": name,
        "course_id": course_id,
        "section_id": None,
        "subsection_id": None,
        "prev_id": None,
        "next_id": None,
        "prev_in_subsection_id": None,
        "next_in_subsection_id": None,
        "children": [],
        "_parents": [],
    }


def _merge_graph_topics(
    topics_by_id: dict[str, dict[str, Any]],
    graph_topics: dict[int, dict[str, Any]],
    *,
    course_id: int,
    course_topic_ids: set[int],
) -> None:
    for topic_id, graph_topic in graph_topics.items():
        if topic_id not in course_topic_ids:
            continue
        key = str(topic_id)
        if key not in topics_by_id:
            topics_by_id[key] = _topic_doc(
                topic_id,
                name=str(graph_topic.get("name") or ""),
                course_id=course_id,
            )
        topic_doc = topics_by_id[key]
        topic_doc["name"] = topic_doc["name"] or str(graph_topic.get("name") or "")
        prerequisites = [
            prereq_id
            for prereq_id in graph_topic.get("prerequisites", [])
            if isinstance(prereq_id, int) and prereq_id in course_topic_ids
        ]
        topic_doc["_parents"] = prerequisites


def _add_placements(
    topics_by_id: dict[str, dict[str, Any]],
    placements_by_topic_id: dict[int, list[dict[str, Any]]],
) -> None:
    for topic_id, placements in placements_by_topic_id.items():
        topic_doc = topics_by_id[str(topic_id)]
        if placements:
            topic_doc["course_id"] = placements[0]["course_id"]
            topic_doc["section_id"] = placements[0]["section_id"]
            topic_doc["subsection_id"] = placements[0]["subsection_id"]


def _add_course_neighbors(
    ordered_topic_ids: list[int],
    topics_by_id: dict[str, dict[str, Any]],
) -> None:
    for index, topic_id in enumerate(ordered_topic_ids):
        topic_doc = topics_by_id[str(topic_id)]
        topic_doc["prev_id"] = (
            ordered_topic_ids[index - 1] if index > 0 else None
        )
        topic_doc["next_id"] = (
            ordered_topic_ids[index + 1]
            if index + 1 < len(ordered_topic_ids)
            else None
        )


def _add_module_neighbors(
    module_topic_ids: list[int],
    topics_by_id: dict[str, dict[str, Any]],
) -> None:
    for index, topic_id in enumerate(module_topic_ids):
        topic_doc = topics_by_id[str(topic_id)]
        topic_doc["prev_in_subsection_id"] = (
            module_topic_ids[index - 1] if index > 0 else None
        )
        topic_doc["next_in_subsection_id"] = (
            module_topic_ids[index + 1]
            if index + 1 < len(module_topic_ids)
            else None
        )


def _add_dependent_edges(topics_by_id: dict[str, dict[str, Any]]) -> None:
    dependents_by_topic_id: dict[int, list[int]] = defaultdict(list)
    for topic in topics_by_id.values():
        topic_id = topic["id"]
        for prerequisite_id in topic["_parents"]:
            dependents_by_topic_id[prerequisite_id].append(topic_id)

    for topic in topics_by_id.values():
        dependents = sorted(dependents_by_topic_id.get(topic["id"], []))
        topic["children"] = dependents
        topic.pop("_parents", None)


def _course_name(
    course_id: int,
    content: dict[str, Any],
    graph_topics: dict[int, dict[str, Any]],
) -> str:
    for topic in graph_topics.values():
        course = topic.get("course")
        if isinstance(course, dict) and course.get("id") == course_id:
            name = course.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    name = content.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else ""


def _int_key(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _expect_int(value: Any, label: str) -> int:
    if isinstance(value, int):
        return value
    raise InvalidResponseError(f"Unexpected Math Academy response: missing {label}.")
