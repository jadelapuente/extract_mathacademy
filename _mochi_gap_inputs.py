from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, data: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def build_gap_groups(
    course_graph: dict[str, Any],
    groups_doc: dict[str, Any],
    *,
    include_same_subsection_context: bool = False,
) -> list[dict[str, Any]]:
    curriculum = _curriculum_view(course_graph)
    topics_by_id = course_graph["topics_by_id"]
    subsections_by_id = curriculum["subsections_by_id"]

    gap_groups: list[dict[str, Any]] = []
    for index, group in enumerate(groups_doc.get("groups", []), start=1):
        source_topic_ids = _group_topic_ids(group)
        target_topic_ids = [
            topic_id for topic_id in source_topic_ids if str(topic_id) in topics_by_id
        ]
        target_id_set = {str(topic_id) for topic_id in target_topic_ids}
        missing_topic_ids = [
            topic_id for topic_id in source_topic_ids if str(topic_id) not in topics_by_id
        ]
        target_topics = [
            _topic_summary(topics_by_id[str(topic_id)], curriculum)
            for topic_id in target_topic_ids
        ]

        context_topics = _build_context_topics(
            target_topic_ids,
            topics_by_id,
            target_id_set,
            include_same_subsection_context=include_same_subsection_context,
            subsections_by_id=subsections_by_id,
            curriculum=curriculum,
        )

        gap_groups.append(
            {
                "id": group.get("slug") or f"group-{index}",
                "name": group.get("name"),
                "target_topics": target_topics,
                "context_topics": context_topics,
                "missing_topic_ids": missing_topic_ids,
            }
        )

    return gap_groups


def groups_doc_from_topic_ids(
    topic_ids: list[int],
    course_graph: dict[str, Any],
) -> dict[str, Any]:
    topics_by_id = course_graph["topics_by_id"]
    return {
        "schema_version": 1,
        "grouping": "single-topic",
        "groups": [
            {
                "slug": f"topic-{topic_id}",
                "name": topics_by_id.get(str(topic_id), {}).get(
                    "name",
                    f"Topic {topic_id}",
                ),
                "topic_ids": [topic_id],
            }
            for topic_id in topic_ids
        ],
    }


def prepare_mochi_decks(
    raw_decks: list[dict[str, Any]] | dict[str, Any],
    *,
    root_deck_id: str | None = None,
    root_deck_name: str = "Math",
) -> list[dict[str, Any]]:
    decks = _deck_docs(raw_decks)
    deck_by_id = {deck["id"]: deck for deck in decks}
    root = _find_root_deck(decks, root_deck_id=root_deck_id, name=root_deck_name)
    children_by_parent = _children_by_parent(decks)
    root_id = root["id"]

    candidates: list[dict[str, Any]] = []
    stack: list[tuple[str, list[str]]] = [(root_id, [root["name"]])]
    visited: set[str] = set()
    while stack:
        deck_id, path_parts = stack.pop()
        if deck_id in visited:
            continue
        visited.add(deck_id)
        deck = deck_by_id[deck_id]
        path = " / ".join(path_parts)
        children = children_by_parent.get(deck_id, [])
        candidates.append(
            {
                "id": deck_id,
                "name": deck.get("name"),
                "parent_id": deck.get("parent-id") or deck.get("parent_id"),
                "path": path,
            }
        )
        for child in reversed(children):
            stack.append((child["id"], path_parts + [child["name"]]))

    return candidates


def build_llm_judging_inputs(
    gap_groups: list[dict[str, Any]],
    mochi_decks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_deck_ids = [deck["id"] for deck in mochi_decks]
    return [
        {
            "gap_group_id": group["id"],
            "candidate_deck_ids": candidate_deck_ids,
        }
        for group in gap_groups
    ]


def build_gap_inputs(
    course_graph: dict[str, Any],
    groups_doc: dict[str, Any],
    raw_decks: list[dict[str, Any]] | dict[str, Any],
    *,
    mochi_root_deck_id: str | None = None,
    mochi_root_deck_name: str = "Math",
    include_same_subsection_context: bool = False,
) -> dict[str, Any]:
    gap_groups = build_gap_groups(
        course_graph,
        groups_doc,
        include_same_subsection_context=include_same_subsection_context,
    )
    mochi_decks = prepare_mochi_decks(
        raw_decks,
        root_deck_id=mochi_root_deck_id,
        root_deck_name=mochi_root_deck_name,
    )
    return {
        "gap_groups": gap_groups,
        "mochi_decks": mochi_decks,
        "llm_deck_judging_units": build_llm_judging_inputs(gap_groups, mochi_decks),
    }


def _group_topic_ids(group: dict[str, Any]) -> list[Any]:
    if "topic_ids" in group:
        return list(group["topic_ids"])
    return [topic["topic_id"] for topic in group.get("topics", [])]


def _curriculum_view(course_graph: dict[str, Any]) -> dict[str, Any]:
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
        "section_ids": _dedupe_preserve_order(section_ids),
        "subsection_ids": _dedupe_preserve_order(subsection_ids),
        "section_by_id": section_by_id,
        "subsections_by_id": subsections_by_id,
    }


def _topic_summary(
    topic: dict[str, Any],
    curriculum: dict[str, Any],
    *,
    relation: str | None = None,
    source_topic_id: Any = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": topic.get("id"),
        "name": topic.get("name"),
        "placements": _placement_summaries(topic, curriculum),
    }
    if relation is not None:
        summary["relation"] = relation
        summary["source_topic_id"] = source_topic_id
    return summary


def _placement_summaries(
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


def _name_by_id(items_by_id: dict[str, dict[str, Any]], item_id: Any) -> str | None:
    item = items_by_id.get(str(item_id))
    name = item.get("name") if item else None
    return name if isinstance(name, str) else None


def _single_course_id(curriculum: dict[str, Any]) -> Any:
    course_ids = curriculum["course_ids"]
    return course_ids[0] if len(course_ids) == 1 else None


def _build_context_topics(
    target_topic_ids: list[Any],
    topics_by_id: dict[str, dict[str, Any]],
    target_id_set: set[str],
    *,
    include_same_subsection_context: bool,
    subsections_by_id: dict[str, dict[str, Any]],
    curriculum: dict[str, Any],
) -> list[dict[str, Any]]:
    context_topics: list[dict[str, Any]] = []

    seen_context_ids: set[str] = set()
    for source_topic_id in target_topic_ids:
        source = topics_by_id[str(source_topic_id)]
        for child_id in source.get("children", []):
            _append_context_topic(
                context_topics,
                topics_by_id,
                child_id,
                target_id_set,
                seen_context_ids,
                relation="child",
                source_topic_id=source_topic_id,
                curriculum=curriculum,
            )
        for relation in ("prev_id", "next_id"):
            neighbor_id = source.get(relation)
            _append_context_topic(
                context_topics,
                topics_by_id,
                neighbor_id,
                target_id_set,
                seen_context_ids,
                relation=relation.replace("_id", ""),
                source_topic_id=source_topic_id,
                curriculum=curriculum,
            )

    if include_same_subsection_context:
        touched_subsections = _dedupe_preserve_order(
            topics_by_id[str(topic_id)].get("subsection_id")
            for topic_id in target_topic_ids
        )
        for subsection_id in touched_subsections:
            subsection = subsections_by_id.get(str(subsection_id), {})
            for topic_id in subsection.get("topic_ids", []):
                _append_context_topic(
                    context_topics,
                    topics_by_id,
                    topic_id,
                    target_id_set,
                    seen_context_ids,
                    relation="same_subsection",
                    source_topic_id=None,
                    curriculum=curriculum,
                )

    return context_topics


def _append_context_topic(
    output: list[dict[str, Any]],
    topics_by_id: dict[str, dict[str, Any]],
    topic_id: Any,
    target_id_set: set[str],
    seen_context_ids: set[str],
    *,
    relation: str,
    source_topic_id: Any,
    curriculum: dict[str, Any],
) -> None:
    if topic_id is None:
        return
    key = str(topic_id)
    if key in target_id_set or key in seen_context_ids or key not in topics_by_id:
        return
    output.append(
        _topic_summary(
            topics_by_id[key],
            curriculum,
            relation=relation,
            source_topic_id=source_topic_id,
        )
    )
    seen_context_ids.add(key)


def _dedupe_preserve_order(values: Any) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if value is None or key in seen:
            continue
        output.append(value)
        seen.add(key)
    return output


def _deck_docs(raw_decks: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw_decks, dict):
        docs = raw_decks.get("docs", [])
    else:
        docs = raw_decks
    return sorted(
        [deck for deck in docs if not deck.get("archived?") and not deck.get("trashed?")],
        key=lambda deck: (deck.get("sort", 0), deck.get("name", ""), deck.get("id", "")),
    )


def _find_root_deck(
    decks: list[dict[str, Any]],
    *,
    root_deck_id: str | None,
    name: str,
) -> dict[str, Any]:
    if root_deck_id:
        for deck in decks:
            if deck["id"] == root_deck_id:
                return deck
        raise ValueError(f"could not find Mochi root deck id: {root_deck_id}")

    normalized_name = name.casefold()
    matches = [deck for deck in decks if deck.get("name", "").casefold() == normalized_name]
    if not matches:
        raise ValueError(f"could not find Mochi root deck named: {name}")
    top_level_matches = [
        deck
        for deck in matches
        if not (deck.get("parent-id") or deck.get("parent_id"))
    ]
    return (top_level_matches or matches)[0]


def _children_by_parent(decks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[dict[str, Any]]] = {}
    deck_ids = {deck["id"] for deck in decks}
    for deck in decks:
        parent_id = deck.get("parent-id") or deck.get("parent_id")
        if parent_id in deck_ids:
            children.setdefault(parent_id, []).append(deck)
    for child_decks in children.values():
        child_decks.sort(
            key=lambda deck: (deck.get("sort", 0), deck.get("name", ""), deck["id"])
        )
    return children
