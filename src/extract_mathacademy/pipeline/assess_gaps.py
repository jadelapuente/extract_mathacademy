from __future__ import annotations

from typing import Any

from extract_mathacademy.curriculum.views import (
    topic_summary,
)
from extract_mathacademy.io.json_files import load_json, write_json
from extract_mathacademy.mochi.decks import prepare_mochi_decks

ContextTopicRef = tuple[Any, str, Any]


def build_gap_groups(
    course_graph: dict[str, Any],
    groups_doc: dict[str, Any],
    *,
    include_next_context: bool = False,
) -> list[dict[str, Any]]:
    topics_by_id = course_graph["topics_by_id"]

    gap_groups: list[dict[str, Any]] = []
    for index, group in enumerate(groups_doc.get("groups", []), start=1):
        source_topic_ids = _group_topic_ids(group)
        target_topic_ids = [
            topic_id for topic_id in source_topic_ids if str(topic_id) in topics_by_id
        ]
        target_id_set = {str(topic_id) for topic_id in target_topic_ids}
        target_topics = [
            topic_summary(topics_by_id[str(topic_id)])
            for topic_id in target_topic_ids
        ]

        context_topics = _build_context_topics(
            target_topic_ids,
            topics_by_id,
            target_id_set,
            include_next_context=include_next_context,
        )

        gap_groups.append(
            {
                "id": group.get("slug") or f"group-{index}",
                "name": group.get("name"),
                "target_topics": target_topics,
                "context_topics": context_topics,
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
    include_next_context: bool = False,
) -> dict[str, Any]:
    gap_groups = build_gap_groups(
        course_graph,
        groups_doc,
        include_next_context=include_next_context,
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


def build_missing_topics_report(
    course_graph: dict[str, Any],
    groups_doc: dict[str, Any],
) -> dict[str, Any] | None:
    topics_by_id = course_graph["topics_by_id"]
    groups: list[dict[str, Any]] = []
    total_missing = 0

    for index, group in enumerate(groups_doc.get("groups", []), start=1):
        missing_topic_ids = [
            topic_id
            for topic_id in _group_topic_ids(group)
            if str(topic_id) not in topics_by_id
        ]
        if not missing_topic_ids:
            continue

        total_missing += len(missing_topic_ids)
        groups.append(
            {
                "gap_group_id": group.get("slug") or f"group-{index}",
                "gap_group_name": group.get("name"),
                "missing_topic_ids": missing_topic_ids,
            }
        )

    if not groups:
        return None

    return {
        "total_missing_topic_ids": total_missing,
        "groups": groups,
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
    include_next_context: bool,
) -> list[dict[str, Any]]:
    return [
        {
            **topic_summary(topics_by_id[str(topic_id)]),
            "relations": relations,
        }
        for topic_id, relations in _context_topics_with_relations(
            _context_topic_refs(
                target_topic_ids,
                topics_by_id,
                include_next_context=include_next_context,
            ),
            topics_by_id,
            target_id_set,
        )
    ]


def _context_topic_refs(
    target_topic_ids: list[Any],
    topics_by_id: dict[str, dict[str, Any]],
    *,
    include_next_context: bool,
) -> list[ContextTopicRef]:
    return [
        ref
        for source_topic_id in target_topic_ids
        for ref in _direct_context_refs(
            source_topic_id,
            topics_by_id[str(source_topic_id)],
            include_next_context=include_next_context,
        )
    ]


def _direct_context_refs(
    source_topic_id: Any,
    source: dict[str, Any],
    *,
    include_next_context: bool,
) -> list[ContextTopicRef]:
    child_refs = [
        (child_id, "child", source_topic_id)
        for child_id in source.get("children", [])
    ]
    neighbor_ref_names = ["prev_id"]
    if include_next_context:
        neighbor_ref_names.append("next_id")
    neighbor_refs = [
        (source.get(relation), relation.replace("_id", ""), source_topic_id)
        for relation in neighbor_ref_names
    ]
    return child_refs + neighbor_refs


def _context_topics_with_relations(
    refs: list[ContextTopicRef],
    topics_by_id: dict[str, dict[str, Any]],
    target_id_set: set[str],
) -> list[tuple[Any, list[dict[str, Any]]]]:
    output: list[tuple[Any, list[dict[str, Any]]]] = []
    relations_by_context_id: dict[str, list[dict[str, Any]]] = {}
    seen_relation_keys: set[tuple[str, str, str]] = set()

    for topic_id, relation, source_topic_id in refs:
        if topic_id is None:
            continue
        key = str(topic_id)
        if key in target_id_set or key not in topics_by_id:
            continue

        relation_key = (key, relation, str(source_topic_id))
        if relation_key in seen_relation_keys:
            continue

        relation_summary = {
            "relation": relation,
            "source_topic_id": source_topic_id,
        }
        if key not in relations_by_context_id:
            relations_by_context_id[key] = []
            output.append((topic_id, relations_by_context_id[key]))

        relations_by_context_id[key].append(relation_summary)
        seen_relation_keys.add(relation_key)

    return output
