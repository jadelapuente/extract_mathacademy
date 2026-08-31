from __future__ import annotations

from typing import TypeAlias, TypedDict


class BaseStep(TypedDict):
    id: str | None
    type: str
    title: str


class TutorialStep(BaseStep):
    body: str


class ExampleStep(BaseStep):
    question: str
    explanation: str


LessonStep: TypeAlias = TutorialStep | ExampleStep
