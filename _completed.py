from __future__ import annotations

import json
import sys
from datetime import date as dt_date
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol, TextIO
from zoneinfo import ZoneInfo

from _client import MA_BASE_URL, fetch_html, fetch_previous_tasks, session_cookies
from _writer import write_extracted_lesson


class FetchPreviousTasks(Protocol):
    def __call__(self, before: datetime, cookies: Any = None) -> list[dict[str, Any]]:
        ...


class CompletedTopicIds(Protocol):
    def __call__(
        self,
        start_date: dt_date,
        end_date: dt_date,
        *,
        timezone: str = "America/Los_Angeles",
        cookies: Any = None,
        include_review_topics: bool = False,
    ) -> list[int]:
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
    seen_topic_ids: dict[int, None] = {}

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
            if task.get("type") not in allowed_types:
                continue

            topic = task.get("topic") or {}
            topic_id = topic.get("id")
            if isinstance(topic_id, int):
                seen_topic_ids.setdefault(topic_id, None)

        if oldest_completed is None or oldest_completed < start_utc:
            break
        if oldest_completed >= cursor:
            break
        cursor = oldest_completed

    return list(seen_topic_ids)


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
    completed_topic_ids_fn: CompletedTopicIds = completed_topic_ids,
    fetch_html_fn: FetchHtml = fetch_html,
    write_extracted_lesson_fn: WriteExtractedLesson = write_extracted_lesson,
    base_url: str = MA_BASE_URL,
    stderr: TextIO | None = None,
) -> tuple[Path, list[int]]:
    if end_date < start_date:
        raise ValueError("end date must be on or after start date")

    stderr = stderr if stderr is not None else sys.stderr
    cookies = session_cookies_fn()
    topic_ids = completed_topic_ids_fn(
        start_date,
        end_date,
        timezone=timezone,
        cookies=cookies,
        include_review_topics=include_review_topics,
    )

    range_dir = out_dir / f"{start_date.isoformat()}-to-{end_date.isoformat()}"
    range_dir.mkdir(parents=True, exist_ok=True)
    (range_dir / "topic_ids.json").write_text(
        json.dumps(topic_ids, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest: list[dict[str, Any]] = []
    for index, topic_id in enumerate(topic_ids, start=1):
        url = f"{base_url}/topics/{topic_id}"
        html = fetch_html_fn(url, cookies)
        out_path, step_count = write_extracted_lesson_fn(
            html,
            fallback_name=str(topic_id),
            fmt=fmt,
            out_dir=range_dir,
            source_url=url,
            cookies=cookies,
            no_images=no_images,
        )
        manifest.append({
            "topic_id": topic_id,
            "url": url,
            "output": str(out_path),
            "steps": step_count,
        })
        print(
            f"[{index}/{len(topic_ids)}] wrote {step_count} steps -> {out_path}",
            file=stderr,
        )

    (range_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return range_dir, topic_ids
