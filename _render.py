from __future__ import annotations

import json
from typing import Any, Mapping

from _model import ExampleStep, LessonStep, TutorialStep, step_to_dict


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #

def _coerce_step(step: LessonStep | Mapping[str, Any]) -> LessonStep:
    if isinstance(step, (TutorialStep, ExampleStep)):
        return step
    if "body" in step:
        return TutorialStep(
            id=step.get("id"),
            type=step["type"],
            title=step["title"],
            body=step["body"],
        )
    return ExampleStep(
        id=step.get("id"),
        type=step["type"],
        title=step["title"],
        question=step.get("question") or "",
        explanation=step.get("explanation") or "",
    )


def _render_step_markdown(step: LessonStep) -> list[str]:
    out = [f"## [{step.type}] {step.title}".rstrip()]
    if isinstance(step, TutorialStep):
        out.append(step.body)
        return out

    out.extend(
        section
        for section in (
            "**Question**\n\n" + step.question if step.question else "",
            "**Explanation**\n\n" + step.explanation if step.explanation else "",
        )
        if section
    )
    return out


def to_markdown(
    steps: list[LessonStep] | list[Mapping[str, Any]],
    title: str | None = None,
) -> str:
    out = [f"# {title}"] if title else []
    for step in steps:
        out.extend(_render_step_markdown(_coerce_step(step)))
    return "\n\n".join(x for x in out if x).strip() + "\n"


def to_json(steps: list[LessonStep] | list[Mapping[str, Any]]) -> str:
    return json.dumps(
        [step_to_dict(step) for step in steps],
        indent=2,
        ensure_ascii=False,
    ) + "\n"
