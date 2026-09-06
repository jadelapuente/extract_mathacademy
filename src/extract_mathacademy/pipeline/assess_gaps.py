from __future__ import annotations

from typing import Any

from extract_mathacademy.curriculum.views import (
    curriculum_view,
    dedupe_preserve_order,
    topic_summary,
)
from extract_mathacademy.io.json_files import load_json, write_json
from extract_mathacademy.mochi.decks import prepare_mochi_decks

ContextTopicRef = tuple[Any, str, Any]


def build_gap_groups(
    course_graph: dict[str, Any],
    groups_doc: dict[str, Any],
    *,
    include_same_subsection_context: bool = False,
) -> list[dict[str, Any]]:
    curriculum = curriculum_view(course_graph)
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
            topic_summary(topics_by_id[str(topic_id)], curriculum)
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
    all_math_decks = prepare_mochi_decks(
        raw_decks,
        root_deck_id=mochi_root_deck_id,
        root_deck_name=mochi_root_deck_name,
    )
    return {
        "gap_groups": gap_groups,
        "all_math_decks": all_math_decks,
    }


def _group_topic_ids(group: dict[str, Any]) -> list[Any]:
    if "topic_ids" in group:
        return list(group["topic_ids"])
    return [topic["topic_id"] for topic in group.get("topics", [])]


def _build_context_topics(
    target_topic_ids: list[Any],
    topics_by_id: dict[str, dict[str, Any]],
    target_id_set: set[str],
    *,
    include_same_subsection_context: bool,
    subsections_by_id: dict[str, dict[str, Any]],
    curriculum: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        topic_summary(
            topics_by_id[str(topic_id)],
            curriculum,
            relation=relation,
            source_topic_id=source_topic_id,
        )
        for topic_id, relation, source_topic_id in _unique_context_topic_refs(
            _context_topic_refs(
                target_topic_ids,
                topics_by_id,
                include_same_subsection_context=include_same_subsection_context,
                subsections_by_id=subsections_by_id,
            ),
            topics_by_id,
            target_id_set,
        )
    ]


def _context_topic_refs(
    target_topic_ids: list[Any],
    topics_by_id: dict[str, dict[str, Any]],
    *,
    include_same_subsection_context: bool,
    subsections_by_id: dict[str, dict[str, Any]],
) -> list[ContextTopicRef]:
    refs = [
        ref
        for source_topic_id in target_topic_ids
        for ref in _direct_context_refs(
            source_topic_id,
            topics_by_id[str(source_topic_id)],
        )
    ]
    if not include_same_subsection_context:
        return refs

    touched_subsections = dedupe_preserve_order(
        topics_by_id[str(topic_id)].get("subsection_id")
        for topic_id in target_topic_ids
    )
    same_subsection_refs = [
        (topic_id, "same_subsection", None)
        for subsection_id in touched_subsections
        for topic_id in subsections_by_id.get(str(subsection_id), {}).get(
            "topic_ids",
            [],
        )
    ]
    return refs + same_subsection_refs


def _direct_context_refs(
    source_topic_id: Any,
    source: dict[str, Any],
) -> list[ContextTopicRef]:
    child_refs = [
        (child_id, "child", source_topic_id)
        for child_id in source.get("children", [])
    ]
    neighbor_refs = [
        (source.get(relation), relation.replace("_id", ""), source_topic_id)
        for relation in ("prev_id", "next_id")
    ]
    return child_refs + neighbor_refs


def _unique_context_topic_refs(
    refs: list[ContextTopicRef],
    topics_by_id: dict[str, dict[str, Any]],
    target_id_set: set[str],
) -> list[ContextTopicRef]:
    output: list[ContextTopicRef] = []
    seen_context_ids: set[str] = set()
    for topic_id, relation, source_topic_id in refs:
        if topic_id is None:
            continue
        key = str(topic_id)
        if key in target_id_set or key in seen_context_ids or key not in topics_by_id:
            continue
        output.append((topic_id, relation, source_topic_id))
        seen_context_ids.add(key)
    return output
