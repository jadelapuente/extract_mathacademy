#!/usr/bin/env python3
"""
Extract questions, prose, and math notation from Math Academy lesson HTML,
stripping presentational markup and recovering LaTeX.

Patterns exploited
-------------------
1. Each lesson chunk is a  <div class="step" steptype="tutorial|example">.
     - Title:       div.stepName > a.stepAnchor   (examples prefix "Example:")
     - Question:    div.exampleQuestion           (examples only)
     - Explanation: div.exampleExplanation        (examples only)
     - Tutorials:   the <p> children of the step div
2. Every formula is a  <span class="mjpage">  (inline) or
   <span class="mjpage mjpage__block">  (display/block).
3. The math source lives in the SVG's <title>, NOT in the drawn paths:
     - MathJax v2 output -> <title> holds raw LaTeX as text.
     - MathJax v3 output -> <title> holds MathML (<math>...</math>); convert it.
4. Inline <style>/<script>, the "EXPLANATION" header and "?" buttons are noise.

Usage
-----
    python extract_mathacademy.py lesson.html            # markdown to stdout
    python extract_mathacademy.py lesson.html --json      # structured JSON
    cat lesson.html | python extract_mathacademy.py       # stdin also works
"""
import re
import sys
import json
from bs4 import BeautifulSoup, NavigableString, Tag

# --------------------------------------------------------------------------- #
# MathML -> LaTeX  (covers the subset Math Academy's MathJax v3 output emits)  #
# --------------------------------------------------------------------------- #

_OPS = {
    "\u2212": "-",          # minus sign
    "\u22c5": " \\cdot ",   # dot operator
    "\u00d7": " \\times ",
    "\u00b1": " \\pm ",
    "\u2713": " \\checkmark ",
    "\u221e": "\\infty",
    "\u2264": " \\le ",
    "\u2265": " \\ge ",
    "\u2260": " \\ne ",
}


def _map_text(s: str) -> str:
    return "".join(_OPS.get(ch, ch) for ch in s)


def _elems(node: Tag):
    """Child *elements* only (skip whitespace text nodes)."""
    return [c for c in node.children if isinstance(c, Tag)]


def _wrap(s: str) -> str:
    """Brace-wrap a sub-expression for use as a super/subscript base."""
    return s if len(s) <= 1 else "{" + s + "}"


def mathml_to_latex(node) -> str:
    if isinstance(node, NavigableString):
        return _map_text(str(node))
    if not isinstance(node, Tag):
        return ""

    tag = node.name.lower()
    conv = mathml_to_latex

    if tag in ("math", "semantics", "mstyle", "mpadded"):
        return "".join(conv(c) for c in node.children)

    if tag == "mrow":
        cls = node.get("data-mjx-texclass")
        inner = "".join(conv(c) for c in node.children)
        if cls in ("OPEN", "CLOSE"):
            # a stretchy delimiter wrapped on its own (e.g. big "(")
            ch = node.get_text().strip() or "."
            ch = _map_text(ch)
            return ("\\left" if cls == "OPEN" else "\\right") + ch
        return inner  # INNER delimiters are emitted by their own <mo>s

    if tag == "mi":
        return _map_text(node.get_text())

    if tag == "mn":
        return node.get_text()

    if tag == "mo":
        t = _map_text(node.get_text().strip())
        cls = node.get("data-mjx-texclass")
        if cls == "OPEN":
            return "\\left" + (t or ".")
        if cls == "CLOSE":
            return "\\right" + (t or ".")
        return t

    if tag == "mtext":
        t = node.get_text()
        return "\\text{" + t + "}" if t.strip() else ""

    if tag == "mspace":
        return ""

    if tag in ("msup", "msub"):
        e = _elems(node)
        if len(e) >= 2:
            op = "^" if tag == "msup" else "_"
            return f"{_wrap(conv(e[0]))}{op}{{{conv(e[1])}}}"
        return "".join(conv(c) for c in e)

    if tag == "msubsup":
        e = _elems(node)
        if len(e) >= 3:
            return f"{_wrap(conv(e[0]))}_{{{conv(e[1])}}}^{{{conv(e[2])}}}"

    if tag == "mfrac":
        e = _elems(node)
        if len(e) >= 2:
            return f"\\frac{{{conv(e[0])}}}{{{conv(e[1])}}}"

    if tag == "msqrt":
        return "\\sqrt{" + "".join(conv(c) for c in node.children) + "}"

    if tag == "mroot":
        e = _elems(node)
        if len(e) >= 2:
            return f"\\sqrt[{conv(e[1])}]{{{conv(e[0])}}}"

    if tag == "mtable":
        rows = [r for r in _elems(node) if r.name == "mtr"]
        rendered = []
        for r in rows:
            cells = [conv_cell(c) for c in _elems(r) if c.name == "mtd"]
            rendered.append(" & ".join(cells))
        if len(rendered) > 1:
            body = " \\\\ ".join(x.strip() for x in rendered)
            return "\\begin{aligned} " + body + " \\end{aligned}"
        return rendered[0] if rendered else ""

    # Fallback: concatenate children.
    return "".join(conv(c) for c in node.children)


def conv_cell(mtd: Tag) -> str:
    return "".join(mathml_to_latex(c) for c in mtd.children).strip()


# --------------------------------------------------------------------------- #
# Span -> LaTeX                                                                #
# --------------------------------------------------------------------------- #

def mjpage_to_latex(span: Tag) -> str:
    svg = span.find("svg")
    title = svg.find("title") if svg else None
    if title is None:
        return ""
    math = title.find("math")
    if math is not None:                       # MathJax v3: MathML in title
        latex = mathml_to_latex(math)
    else:                                      # MathJax v2: raw LaTeX in title
        latex = re.sub(r"\s+", " ", title.get_text())
    latex = latex.strip()
    is_block = "mjpage__block" in span.get("class", [])
    return f"\n$$ {latex} $$\n" if is_block else f"${latex}$"


# --------------------------------------------------------------------------- #
# DOM -> text                                                                  #
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
    if "helpButton" in cls or "explanationHeader" in cls:
        return ""
    return "".join(node_text(c) for c in node.children)


def clean(s: str) -> str:
    s = s.replace("\xa0", " ")
    s = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines())
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# --------------------------------------------------------------------------- #
# Extraction                                                                   #
# --------------------------------------------------------------------------- #

def extract_steps(html: str):
    soup = BeautifulSoup(html, "html.parser")
    steps = []
    for step in soup.select("div.step"):
        anchor = step.select_one(".stepName a.stepAnchor")
        rec = {
            "id": step.get("stepid"),
            "type": step.get("steptype", ""),
            "title": clean(node_text(anchor)) if anchor else "",
        }
        q = step.select_one(".exampleQuestion")
        e = step.select_one(".exampleExplanation")
        if q is not None or e is not None:
            rec["question"] = clean(node_text(q)) if q else ""
            rec["explanation"] = clean(node_text(e)) if e else ""
        else:
            paras = [clean(node_text(p)) for p in step.find_all("p")]
            rec["body"] = "\n\n".join(p for p in paras if p)
        steps.append(rec)
    return steps


def to_markdown(steps) -> str:
    out = []
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


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv
    html = open(args[0], encoding="utf-8").read() if args else sys.stdin.read()
    steps = extract_steps(html)
    if as_json:
        print(json.dumps(steps, indent=2, ensure_ascii=False))
    else:
        print(to_markdown(steps))


if __name__ == "__main__":
    main(sys.argv)
