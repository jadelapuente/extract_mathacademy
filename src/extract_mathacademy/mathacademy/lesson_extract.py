from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from extract_mathacademy.mathacademy.models import ExampleStep, LessonStep, TutorialStep
from extract_mathacademy.mathacademy.mathml import mjpage_to_latex


# --------------------------------------------------------------------------- #
# DOM -> text                                                                 #
# --------------------------------------------------------------------------- #

def node_text(node) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name in ("style", "script"):
        return ""
    cls = node.get("class", [])
    if node.name == "span" and "mjpage" in cls:
        return mjpage_to_latex(node)
    if node.name == "img":
        src = node.get("src", "")
        alt = (node.get("alt") or "").strip()
        return f"![{alt}]({src})" if src else ""
    if "helpButton" in cls or "explanationHeader" in cls:
        return ""
    return "".join(node_text(c) for c in node.children)


def clean(s: str) -> str:
    """Tidy a multi-paragraph block: trim lines, collapse blank-line runs."""
    s = s.replace("\xa0", " ")
    s = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines())
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def clean_inline(s: str) -> str:
    """Tidy a value that must stay on one line (e.g. a title)."""
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


# --------------------------------------------------------------------------- #
# Extraction                                                                  #
# --------------------------------------------------------------------------- #

def extract_steps(html: str) -> list[LessonStep]:
    soup = BeautifulSoup(html, "html.parser")
    steps: list[LessonStep] = []
    for step in soup.select("div.step"):
        anchor = step.select_one(".stepName a.stepAnchor")
        base = {
            "id": step.get("stepid"),
            "type": step.get("steptype", ""),
            "title": clean_inline(node_text(anchor)) if anchor else "",
        }
        q = step.select_one(".exampleQuestion")
        e = step.select_one(".exampleExplanation")
        if q is not None or e is not None:
            rec = ExampleStep(
                **base,
                question=clean(node_text(q)) if q else "",
                explanation=clean(node_text(e)) if e else "",
            )
        else:
            parts = []
            for node in step.find_all(["p", "img"]):
                if node.name == "img" and node.find_parent("p"):
                    continue  # already rendered inline by its paragraph
                t = clean(node_text(node))
                if t:
                    parts.append(t)
            rec = TutorialStep(
                **base,
                body="\n\n".join(parts),
            )
        steps.append(rec)
    return steps


def extract_title(html: str) -> str | None:
    """The lesson's human title, from the page's #topicName element."""
    el = BeautifulSoup(html, "html.parser").select_one("#topicName")
    title = clean_inline(el.get_text()) if el else ""
    return title or None


def topic_id_from_href(href: str) -> int | None:
    path = urlparse(href).path.rstrip("/")
    if not path.startswith("/topics/"):
        return None
    match = re.search(r"(?:^|[-/])(\d+)$", path)
    return int(match.group(1)) if match else None


def extract_prerequisite_topic_ids(html: str) -> list[int]:
    soup = BeautifulSoup(html, "html.parser")
    ids: dict[int, None] = {}
    for anchor in soup.select("a.prerequisiteLink[href]"):
        topic_id = topic_id_from_href(anchor.get("href", ""))
        if topic_id is not None:
            ids.setdefault(topic_id, None)
    return list(ids)


def slugify(text: str) -> str:
    """Filesystem-safe slug, e.g. 'Inverses of Quadratic Functions' ->
    'inverses-of-quadratic-functions'."""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "lesson"
