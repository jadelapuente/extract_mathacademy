from __future__ import annotations

import json
from typing import Any, Mapping

from _model import ExampleStep, LessonStep, TutorialStep, step_to_dict


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #

def to_markdown(
    steps: list[LessonStep] | list[Mapping[str, Any]],
    title: str | None = None,
) -> str:
    out = [f"# {title}"] if title else []
    for s in steps:
        if isinstance(s, TutorialStep):
            out.append(f"## [{s.type}] {s.title}".rstrip())
            out.append(s.body)
        elif isinstance(s, ExampleStep):
            out.append(f"## [{s.type}] {s.title}".rstrip())
            if s.question:
                out.append("**Question**\n\n" + s.question)
            if s.explanation:
                out.append("**Explanation**\n\n" + s.explanation)
        else:
            out.append(f"## [{s['type']}] {s['title']}".rstrip())
            if "body" in s:
                out.append(s["body"])
                continue
            if s.get("question"):
                out.append("**Question**\n\n" + s["question"])
            if s.get("explanation"):
                out.append("**Explanation**\n\n" + s["explanation"])
    return "\n\n".join(x for x in out if x).strip() + "\n"


def to_json(steps: list[LessonStep] | list[Mapping[str, Any]]) -> str:
    return json.dumps(
        [step_to_dict(step) for step in steps],
        indent=2,
        ensure_ascii=False,
    ) + "\n"
