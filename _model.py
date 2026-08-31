from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping, TypeAlias


@dataclass(frozen=True)
class BaseStep(Mapping[str, Any]):
    id: str | None
    type: str
    title: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True)
class TutorialStep(BaseStep):
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "body": self.body,
        }


@dataclass(frozen=True)
class ExampleStep(BaseStep):
    question: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "question": self.question,
            "explanation": self.explanation,
        }


LessonStep: TypeAlias = TutorialStep | ExampleStep


def step_to_dict(step: LessonStep | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(step, BaseStep):
        return step.to_dict()
    return dict(step)
