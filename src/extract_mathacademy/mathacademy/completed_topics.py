from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from datetime import date as dt_date
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol, TextIO
from zoneinfo import ZoneInfo

from extract_mathacademy.mathacademy.client import MA_BASE_URL, fetch_html, fetch_previous_tasks, session_cookies
from extract_mathacademy.mathacademy.lesson_extract import extract_prerequisite_topic_ids, extract_title
from extract_mathacademy.io.lesson_writer import write_extracted_lesson

NodeId = str | int | None
RelationshipPath = tuple[str, ...]


class FetchPreviousTasks(Protocol):
    def __call__(self, before: datetime, cookies: Any = None) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class CompletedTopicRecord:
    task_id: int | None
    task_type: str
    topic_id: int
    topic_name: str
    completed_at: datetime
    learning_node_id: str | int | None = None
    previous_learning_node_id: str | int | None = None
    next_learning_node_id: str | int | None = None
    prerequisite_topic_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CompletedTopicRelationships:
    learning_node_id: NodeId = None
    previous_learning_node_id: NodeId = None
    next_learning_node_id: NodeId = None


@dataclass(frozen=True)
class CompletedTopicWriteItem:
    group_slug: str
    group_name: str
    record: CompletedTopicRecord
    url: str
    html: str


@dataclass(frozen=True)
class CompletedTopicExtractionPlan:
    range_dir: Path
    topic_ids: list[int]
    groups_doc: dict[str, Any]
    write_items: list[CompletedTopicWriteItem]


class CompletedTopicRecords(Protocol):
    def __call__(
        self,
        start_date: dt_date,
        end_date: dt_date,
        *,
        timezone: str = "America/Los_Angeles",
        cookies: Any = None,
        include_review_topics: bool = False,
    ) -> list[CompletedTopicRecord]:
        ...


class FetchHtml(Protocol):
    def __call__(self, url: str, cookies: Any = None) -> str:
        ...


class WriteExtractedLesson(Protocol):
    def __call__(
        self,
        html: str,
        *,
        fallback_name: str,
        fmt: str,
        out_dir: Path,
        source_url: str | None = None,
        cookies: Any = None,
        no_images: bool = False,
    ) -> tuple[Path, int]:
        ...


def parse_completed_at(task: dict[str, Any]) -> datetime | None:
    completed = task.get("completed")
    if not completed:
        return None
    return datetime.fromisoformat(completed.replace("Z", "+00:00"))


def _path_value(obj: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_path_value(obj: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        value = _path_value(obj, path)
        if value is not None:
            return value
    return None


_LEARNING_NODE_PATHS: tuple[RelationshipPath, ...] = (
    ("task", "learning_node_id"),
    ("task", "learningNodeId"),
    ("task", "node_id"),
    ("task", "nodeId"),
    ("task", "learning_node", "id"),
    ("task", "learningNode", "id"),
    ("task", "node", "id"),
    ("topic", "learning_node_id"),
    ("topic", "learningNodeId"),
    ("topic", "node_id"),
    ("topic", "nodeId"),
    ("topic", "learning_node", "id"),
    ("topic", "learningNode", "id"),
    ("topic", "node", "id"),
)

_PREVIOUS_LEARNING_NODE_PATHS: tuple[RelationshipPath, ...] = (
    ("task", "previous_learning_node_id"),
    ("task", "previousLearningNodeId"),
    ("task", "previous_node_id"),
    ("task", "previousNodeId"),
    ("task", "prerequisite_node_id"),
    ("task", "prerequisiteNodeId"),
    ("task", "learning_node", "previous", "id"),
    ("task", "learningNode", "previous", "id"),
    ("task", "node", "previous", "id"),
    ("topic", "previous_learning_node_id"),
    ("topic", "previousLearningNodeId"),
    ("topic", "previous_node_id"),
    ("topic", "previousNodeId"),
    ("topic", "prerequisite_node_id"),
    ("topic", "prerequisiteNodeId"),
    ("topic", "learning_node", "previous", "id"),
    ("topic", "learningNode", "previous", "id"),
    ("topic", "node", "previous", "id"),
)

_NEXT_LEARNING_NODE_PATHS: tuple[RelationshipPath, ...] = (
    ("task", "next_learning_node_id"),
    ("task", "nextLearningNodeId"),
    ("task", "next_node_id"),
    ("task", "nextNodeId"),
    ("task", "learning_node", "next", "id"),
    ("task", "learningNode", "next", "id"),
    ("task", "node", "next", "id"),
    ("topic", "next_learning_node_id"),
    ("topic", "nextLearningNodeId"),
    ("topic", "next_node_id"),
    ("topic", "nextNodeId"),
    ("topic", "learning_node", "next", "id"),
    ("topic", "learningNode", "next", "id"),
    ("topic", "node", "next", "id"),
)


def _relationship_value(
    combined: dict[str, Any],
    paths: tuple[RelationshipPath, ...],
) -> NodeId:
    value = _first_path_value(combined, paths)
    return value if isinstance(value, (str, int)) else None


def extract_relationships(task: dict[str, Any]) -> CompletedTopicRelationships:
    topic = task.get("topic") if isinstance(task.get("topic"), dict) else {}
    combined = {"task": task, "topic": topic}
    return CompletedTopicRelationships(
        learning_node_id=_relationship_value(combined, _LEARNING_NODE_PATHS),
        previous_learning_node_id=_relationship_value(
            combined,
            _PREVIOUS_LEARNING_NODE_PATHS,
        ),
        next_learning_node_id=_relationship_value(
            combined,
            _NEXT_LEARNING_NODE_PATHS,
        ),
    )


def completed_topic_records(
    start_date: dt_date,
    end_date: dt_date,
    *,
    timezone: str = "America/Los_Angeles",
    cookies=None,
    include_review_topics: bool = False,
    fetch_previous_tasks_fn: FetchPreviousTasks = fetch_previous_tasks,
    session_cookies_fn: Callable[[], Any] = session_cookies,
) -> list[CompletedTopicRecord]:
    """Return unique completed topic records within an inclusive local date range."""
    if end_date < start_date:
        raise ValueError("end date must be on or after start date")

    local_tz = ZoneInfo(timezone)
    utc = ZoneInfo("UTC")
    start_utc = datetime.combine(start_date, time.min, local_tz).astimezone(utc)
    end_exclusive_utc = datetime.combine(
        end_date + timedelta(days=1), time.min, local_tz
    ).astimezone(utc)

    allowed_types = {"Lesson"}
    if include_review_topics:
        allowed_types.add("Review")

    cookies = cookies if cookies is not None else session_cookies_fn()
    cursor = end_exclusive_utc
    seen_task_ids: set[int] = set()
    seen_topic_ids: set[int] = set()
    records: list[CompletedTopicRecord] = []

    while True:
        page = fetch_previous_tasks_fn(cursor, cookies)
        if not page:
            break

        oldest_completed: datetime | None = None
        for task in page:
            completed_at = parse_completed_at(task)
            if completed_at is None:
                continue
            oldest_completed = (
                completed_at
                if oldest_completed is None or completed_at < oldest_completed
                else oldest_completed
            )

            task_id = task.get("id")
            if isinstance(task_id, int):
                if task_id in seen_task_ids:
                    continue
                seen_task_ids.add(task_id)

            if not (start_utc <= completed_at < end_exclusive_utc):
                continue
            task_type = task.get("type")
            if task_type not in allowed_types:
                continue

            topic = task.get("topic") or {}
            topic_id = topic.get("id") if isinstance(topic, dict) else None
            if not isinstance(topic_id, int) or topic_id in seen_topic_ids:
                continue

            seen_topic_ids.add(topic_id)
            topic_name = topic.get("name") if isinstance(topic, dict) else None
            relationships = extract_relationships(task)
            records.append(
                CompletedTopicRecord(
                    task_id=task_id if isinstance(task_id, int) else None,
                    task_type=task_type,
                    topic_id=topic_id,
                    topic_name=topic_name if isinstance(topic_name, str) else "",
                    completed_at=completed_at,
                    learning_node_id=relationships.learning_node_id,
                    previous_learning_node_id=(
                        relationships.previous_learning_node_id
                    ),
                    next_learning_node_id=relationships.next_learning_node_id,
                )
            )

        if oldest_completed is None or oldest_completed < start_utc:
            break
        if oldest_completed >= cursor:
            break
        cursor = oldest_completed

    return records


def completed_topic_ids(
    start_date: dt_date,
    end_date: dt_date,
    *,
    timezone: str = "America/Los_Angeles",
    cookies=None,
    include_review_topics: bool = False,
    fetch_previous_tasks_fn: FetchPreviousTasks = fetch_previous_tasks,
    session_cookies_fn: Callable[[], Any] = session_cookies,
) -> list[int]:
    """Return unique topic ids completed within an inclusive local date range."""
    return [
        record.topic_id
        for record in completed_topic_records(
            start_date,
            end_date,
            timezone=timezone,
            cookies=cookies,
            include_review_topics=include_review_topics,
            fetch_previous_tasks_fn=fetch_previous_tasks_fn,
            session_cookies_fn=session_cookies_fn,
        )
    ]


def enrich_completed_topic_records(
    records: list[CompletedTopicRecord],
    *,
    cookies: Any,
    fetch_html_fn: FetchHtml = fetch_html,
    base_url: str = MA_BASE_URL,
) -> tuple[list[CompletedTopicRecord], dict[int, str]]:
    enriched: list[CompletedTopicRecord] = []
    topic_htmls: dict[int, str] = {}
    for record in records:
        url = f"{base_url}/topics/{record.topic_id}"
        html = fetch_html_fn(url, cookies)
        topic_htmls[record.topic_id] = html
        html_title = extract_title(html)
        enriched.append(
            replace(
                record,
                topic_name=record.topic_name or html_title or "",
                prerequisite_topic_ids=tuple(extract_prerequisite_topic_ids(html)),
            )
        )
    return enriched, topic_htmls


def build_completed_topic_plan(
    records: list[CompletedTopicRecord],
    *,
    range_dir: Path,
    topic_htmls: dict[int, str],
    base_url: str = MA_BASE_URL,
) -> CompletedTopicExtractionPlan:
    from extract_mathacademy.curriculum.grouping import group_completed_topics

    topic_ids = [record.topic_id for record in records]
    groups = group_completed_topics(records)
    write_items = [
        CompletedTopicWriteItem(
            group_slug=group.slug,
            group_name=group.name,
            record=record,
            url=f"{base_url}/topics/{record.topic_id}",
            html=topic_htmls[record.topic_id],
        )
        for group in groups
        for record in group.records
    ]
    groups_doc = {
        "schema_version": 1,
        "grouping": "node-chain",
        "groups": [
            {
                "slug": group.slug,
                "name": group.name,
                "topic_ids": [record.topic_id for record in group.records],
                "topics": [
                    {
                        "topic_id": record.topic_id,
                        "topic_name": record.topic_name,
                        "learning_node_id": record.learning_node_id,
                        "previous_learning_node_id": (
                            record.previous_learning_node_id
                        ),
                        "next_learning_node_id": record.next_learning_node_id,
                        "prerequisite_topic_ids": list(
                            record.prerequisite_topic_ids
                        ),
                    }
                    for record in group.records
                ],
            }
            for group in groups
        ],
    }
    return CompletedTopicExtractionPlan(
        range_dir=range_dir,
        topic_ids=topic_ids,
        groups_doc=groups_doc,
        write_items=write_items,
    )


def extract_completed_topics(
    start_date: dt_date,
    end_date: dt_date,
    *,
    timezone: str,
    out_dir: Path,
    fmt: str,
    no_images: bool,
    include_review_topics: bool,
    session_cookies_fn: Callable[[], Any] = session_cookies,
    completed_topic_records_fn: CompletedTopicRecords = completed_topic_records,
    fetch_html_fn: FetchHtml = fetch_html,
    write_extracted_lesson_fn: WriteExtractedLesson = write_extracted_lesson,
    base_url: str = MA_BASE_URL,
    stderr: TextIO | None = None,
) -> tuple[Path, list[int]]:
    if end_date < start_date:
        raise ValueError("end date must be on or after start date")

    stderr = stderr if stderr is not None else sys.stderr
    cookies = session_cookies_fn()

    range_dir = out_dir / f"{start_date.isoformat()}-to-{end_date.isoformat()}"
    range_dir.mkdir(parents=True, exist_ok=True)

    base_records = completed_topic_records_fn(
        start_date,
        end_date,
        timezone=timezone,
        cookies=cookies,
        include_review_topics=include_review_topics,
    )
    records, topic_htmls = enrich_completed_topic_records(
        base_records,
        cookies=cookies,
        fetch_html_fn=fetch_html_fn,
        base_url=base_url,
    )
    plan = build_completed_topic_plan(
        records,
        range_dir=range_dir,
        topic_htmls=topic_htmls,
        base_url=base_url,
    )

    (range_dir / "topic_ids.json").write_text(
        json.dumps(plan.topic_ids, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest: list[dict[str, Any]] = []
    (range_dir / "groups.json").write_text(
        json.dumps(plan.groups_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for index, item in enumerate(plan.write_items, start=1):
        out_path, step_count = write_extracted_lesson_fn(
            item.html,
            fallback_name=str(item.record.topic_id),
            fmt=fmt,
            out_dir=range_dir / item.group_slug,
            source_url=item.url,
            cookies=cookies,
            no_images=no_images,
        )
        manifest_record = {
            "topic_id": item.record.topic_id,
            "url": item.url,
            "output": str(out_path),
            "steps": step_count,
        }
        manifest_record.update({
            "group_slug": item.group_slug,
            "group_name": item.group_name,
            "topic_name": item.record.topic_name,
            "learning_node_id": item.record.learning_node_id,
            "prerequisite_topic_ids": list(item.record.prerequisite_topic_ids),
        })
        manifest.append(manifest_record)
        print(
            f"[{index}/{len(plan.write_items)}] wrote {step_count} steps -> "
            f"{out_path}",
            file=stderr,
        )

    (range_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return range_dir, plan.topic_ids
