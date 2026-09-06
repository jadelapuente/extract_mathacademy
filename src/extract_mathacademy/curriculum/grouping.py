from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from extract_mathacademy.mathacademy.completed_topics import CompletedTopicRecord
from extract_mathacademy.mathacademy.lesson_extract import slugify


@dataclass(frozen=True)
class TopicChainGroup:
    name: str
    slug: str
    records: list[CompletedTopicRecord]


class GroupNamer(Protocol):
    def __call__(self, records: list[CompletedTopicRecord]) -> str:
        ...


class DeterministicGroupNamer:
    def __call__(self, records: list[CompletedTopicRecord]) -> str:
        return deterministic_group_name(records)


class _UnionFind:
    def __init__(self, values: list[int]):
        self.parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def deterministic_group_name(records: list[CompletedTopicRecord]) -> str:
    names = [
        record.topic_name.strip()
        for record in records
        if record.topic_name.strip()
    ]
    if not names:
        return f"topic-{records[0].topic_id}" if records else "topics"
    if len(names) == 1:
        return names[0]

    split_names = [name.split() for name in names]
    common: list[str] = []
    for words in zip(*split_names):
        lowered = {word.lower() for word in words}
        if len(lowered) != 1:
            break
        common.append(words[0])

    return " ".join(common) if len(common) >= 2 else names[0]


def group_completed_topics(
    records: list[CompletedTopicRecord],
    *,
    namer: GroupNamer | None = None,
) -> list[TopicChainGroup]:
    namer = namer or DeterministicGroupNamer()
    indexed = list(enumerate(records))
    known_topic_ids = {record.topic_id for record in records}
    topic_id_by_node = {
        record.learning_node_id: record.topic_id
        for record in records
        if record.learning_node_id is not None
    }
    edges = _topic_edges(records, known_topic_ids, topic_id_by_node)

    if not edges:
        return _groups_from_components([[record] for record in records], namer)

    union_find = _UnionFind([record.topic_id for record in records])
    for left_topic_id, right_topic_id in edges:
        union_find.union(left_topic_id, right_topic_id)

    components_by_root: dict[int, list[tuple[int, CompletedTopicRecord]]] = {}
    for index, record in indexed:
        root = union_find.find(record.topic_id)
        components_by_root.setdefault(root, []).append((index, record))

    components = list(components_by_root.values())
    components.sort(key=lambda component: min(index for index, _ in component))

    ordered_components = [
        _order_component(component, edges)
        for component in components
    ]
    return _groups_from_components(ordered_components, namer)


def _topic_edges(
    records: list[CompletedTopicRecord],
    known_topic_ids: set[int],
    topic_id_by_node: dict[str | int, int],
) -> list[tuple[int, int]]:
    edges: dict[tuple[int, int], None] = {}
    for record in records:
        for prerequisite_topic_id in record.prerequisite_topic_ids:
            if prerequisite_topic_id in known_topic_ids:
                edges.setdefault((prerequisite_topic_id, record.topic_id), None)

        if record.learning_node_id is None:
            continue
        previous_topic_id = topic_id_by_node.get(record.previous_learning_node_id)
        if previous_topic_id is not None:
            edges.setdefault((previous_topic_id, record.topic_id), None)
        next_topic_id = topic_id_by_node.get(record.next_learning_node_id)
        if next_topic_id is not None:
            edges.setdefault((record.topic_id, next_topic_id), None)

    return list(edges)


def _order_component(
    component: list[tuple[int, CompletedTopicRecord]],
    edges: list[tuple[int, int]],
) -> list[CompletedTopicRecord]:
    if len(component) <= 1:
        return [record for _, record in component]

    by_topic_id = {
        record.topic_id: (index, record)
        for index, record in component
    }
    component_edges = [
        (left, right)
        for left, right in edges
        if left in by_topic_id and right in by_topic_id
    ]
    if not component_edges:
        return [record for _, record in sorted(component)]

    outgoing: dict[int, int] = {}
    incoming: dict[int, int] = {}
    for left, right in component_edges:
        if left in outgoing and outgoing[left] != right:
            return [item[1] for item in sorted(component)]
        if right in incoming and incoming[right] != left:
            return [item[1] for item in sorted(component)]
        outgoing[left] = right
        incoming[right] = left

    starts = [topic_id for topic_id in by_topic_id if topic_id not in incoming]
    if len(starts) != 1:
        return [item[1] for item in sorted(component)]

    ordered_topic_ids: list[int] = []
    seen: set[int] = set()
    cur = starts[0]
    while cur in by_topic_id and cur not in seen:
        seen.add(cur)
        ordered_topic_ids.append(cur)
        if cur not in outgoing:
            break
        cur = outgoing[cur]

    if len(ordered_topic_ids) != len(component):
        return [item[1] for item in sorted(component)]
    return [by_topic_id[topic_id][1] for topic_id in ordered_topic_ids]


def _groups_from_components(
    components: list[list[CompletedTopicRecord]],
    namer: GroupNamer,
) -> list[TopicChainGroup]:
    used_slugs: dict[str, int] = {}
    groups: list[TopicChainGroup] = []
    for records in components:
        name = namer(records).strip() or deterministic_group_name(records)
        base_slug = slugify(name)
        count = used_slugs.get(base_slug, 0) + 1
        used_slugs[base_slug] = count
        slug = base_slug if count == 1 else f"{base_slug}-{count}"
        groups.append(TopicChainGroup(name=name, slug=slug, records=records))
    return groups
