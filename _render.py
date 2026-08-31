from __future__ import annotations

import json

from _model import LessonStep


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #

def to_markdown(steps: list[LessonStep], title: str | None = None) -> str:
    out = [f"# {title}"] if title else []
    for s in steps:
        out.append(f"## [{s['type']}] {s['title']}".rstrip())
        if "body" in s:
            out.append(s["body"])
        else:
            if s.get("question"):
                out.append("**Question**\n\n" + s["question"])
            if s.get("explanation"):
                out.append("**Explanation**\n\n" + s["explanation"])
    return "\n\n".join(x for x in out if x).strip() + "\n"


def to_json(steps: list[LessonStep]) -> str:
    return json.dumps(steps, indent=2, ensure_ascii=False) + "\n"
