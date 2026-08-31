from __future__ import annotations

import re

from bs4 import NavigableString, Tag

# --------------------------------------------------------------------------- #
# MathML -> LaTeX  (covers the subset Math Academy's MathJax v3 output emits)  #
# --------------------------------------------------------------------------- #

_OPS = {
    "−": "-",          # minus sign
    "⋅": " \\cdot ",   # dot operator
    "×": " \\times ",
    "±": " \\pm ",
    "✓": " \\checkmark ",
    "∞": "\\infty",
    "≤": " \\le ",
    "≥": " \\ge ",
    "≠": " \\ne ",
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


def normalize_latex(latex: str) -> str:
    """Collapse all whitespace runs to single spaces and trim.

    LaTeX is whitespace-insensitive between tokens, so this is lossless for the
    math while removing the newlines/indentation MathJax v3's MathML carries
    over. Keeps formulas on one line, which is far cheaper for an LLM to read.
    """
    return re.sub(r"\s+", " ", latex).strip()


# --------------------------------------------------------------------------- #
# Span -> LaTeX                                                               #
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
        latex = title.get_text()
    latex = normalize_latex(latex)
    if not latex:
        return ""
    is_block = "mjpage__block" in span.get("class", [])
    return f"\n$$ {latex} $$\n" if is_block else f"${latex}$"
