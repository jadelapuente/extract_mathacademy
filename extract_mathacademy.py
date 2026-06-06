#!/usr/bin/env python3
"""
Extract questions, prose, and math notation from Math Academy lesson HTML,
stripping presentational markup and recovering LaTeX.

The output is optimized for LLM consumption: compact single-line LaTeX and a
stable structure (Markdown or JSON).

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
    python extract_mathacademy.py https://mathacademy.com/topics/285
    python extract_mathacademy.py https://mathacademy.com/topics/285 --format json
    python extract_mathacademy.py lesson.html        # local file also works
    cat lesson.html | python extract_mathacademy.py  # stdin too

When given a URL, the script reads your existing Math Academy login from your
browser's cookie store (no password needed -- just stay logged in in your
browser) and fetches the page. Math Academy renders math server-side, so a
plain HTTP fetch returns the same SVG the parser already understands.

Output is a self-contained per-lesson folder named after the lesson title:

    inverses-of-quadratic-functions/
        inverses-of-quadratic-functions.md
        images/<downloaded graphics>

Pass --out-dir to choose where that folder is created, or -o for an explicit
output file path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

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

def extract_steps(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    steps: list[dict[str, Any]] = []
    for step in soup.select("div.step"):
        anchor = step.select_one(".stepName a.stepAnchor")
        rec: dict[str, Any] = {
            "id": step.get("stepid"),
            "type": step.get("steptype", ""),
            "title": clean_inline(node_text(anchor)) if anchor else "",
        }
        q = step.select_one(".exampleQuestion")
        e = step.select_one(".exampleExplanation")
        if q is not None or e is not None:
            rec["question"] = clean(node_text(q)) if q else ""
            rec["explanation"] = clean(node_text(e)) if e else ""
        else:
            parts = []
            for node in step.find_all(["p", "img"]):
                if node.name == "img" and node.find_parent("p"):
                    continue  # already rendered inline by its paragraph
                t = clean(node_text(node))
                if t:
                    parts.append(t)
            rec["body"] = "\n\n".join(parts)
        steps.append(rec)
    return steps


def extract_title(html: str) -> str | None:
    """The lesson's human title, from the page's #topicName element."""
    el = BeautifulSoup(html, "html.parser").select_one("#topicName")
    title = clean_inline(el.get_text()) if el else ""
    return title or None


def slugify(text: str) -> str:
    """Filesystem-safe slug, e.g. 'Inverses of Quadratic Functions' ->
    'inverses-of-quadratic-functions'."""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "lesson"


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #

def to_markdown(steps: list[dict[str, Any]], title: str | None = None) -> str:
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


def to_json(steps: list[dict[str, Any]]) -> str:
    return json.dumps(steps, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- #
# Fetching (reuse the browser's existing Math Academy login)                  #
# --------------------------------------------------------------------------- #

MA_DOMAIN = "mathacademy.com"


def _session_cookies():
    """Read the Math Academy `session` cookie from whichever local browser
    you're logged in with. Tries each in turn, skipping any that's locked or
    unreadable (e.g. Safari's permission-gated cookie store)."""
    import browser_cookie3 as bc3

    for name in ("chrome", "brave", "edge", "firefox", "safari"):
        try:
            cj = getattr(bc3, name)(domain_name=MA_DOMAIN)
        except Exception:                           # locked DB, no profile, etc.
            continue
        if any(c.name == "session" for c in cj):
            return cj
    raise SystemExit(
        "Could not find a Math Academy session in any browser. "
        "Log in at https://mathacademy.com, then run this again."
    )


def fetch_html(url: str, cookies=None) -> str:
    import requests

    r = requests.get(
        url,
        cookies=cookies if cookies is not None else _session_cookies(),
        headers={"User-Agent": "Mozilla/5.0"},
        allow_redirects=True,
        timeout=30,
    )
    # Bounced to a login/landing page => the session cookie is stale.
    if "/login" in r.url or 'type="password"' in r.text.lower():
        raise SystemExit(
            f"Got redirected to {r.url} -- your Math Academy session looks "
            "expired. Re-open mathacademy.com in your browser to refresh it."
        )
    r.raise_for_status()
    return r.text


# Content-Type -> file extension for the image formats Math Academy serves.
_IMG_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


def _image_filename(src: str, content_type: str) -> str:
    """Local filename for an image src: keep its own extension if it has one,
    else append the one implied by the Content-Type (graphics srcs are
    extensionless hashes like /graphics/<hash>)."""
    p = Path(urlparse(src).path)
    if p.suffix:
        return p.name
    ext = _IMG_EXT.get(content_type.split(";")[0].strip(), ".img")
    return p.name + ext


def download_images(srcs, base_url: str, out_dir: Path, cookies) -> dict[str, str]:
    """Download each image src (resolved against base_url) into out_dir using
    the session cookie. Returns {original_src: local_filename}."""
    import requests

    mapping: dict[str, str] = {}
    for src in dict.fromkeys(srcs):                 # de-dup, keep order
        r = requests.get(
            urljoin(base_url, src),
            cookies=cookies,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        r.raise_for_status()
        fname = _image_filename(src, r.headers.get("content-type", ""))
        (out_dir / fname).write_bytes(r.content)
        mapping[src] = fname
    return mapping


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _url_stem(url: str) -> Path:
    """Derive an output filename stem from a URL, e.g. .../topics/285 -> 285."""
    name = Path(urlparse(url).path.rstrip("/")).name
    return Path(name or "lesson")


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract Math Academy lesson content from HTML for LLM use.",
    )
    p.add_argument(
        "input", nargs="?",
        help="HTML file to read, or a mathacademy.com URL to fetch using your "
             "browser's existing login (omit to read from stdin).",
    )
    p.add_argument(
        "--format", choices=["markdown", "json"], default="markdown",
        help="Output format (default: markdown).",
    )
    p.add_argument(
        "-o", "--output",
        help="Explicit output file path. Overrides the default per-lesson "
             "folder; images are written to a sibling images/ directory.",
    )
    p.add_argument(
        "--out-dir", default=".",
        help="Root directory under which the per-lesson folder is created "
             "(default: current directory).",
    )
    p.add_argument(
        "--no-images", action="store_true",
        help="Don't download lesson images (URL input only).",
    )
    return p


def run(args: argparse.Namespace) -> int:
    source_url = None
    cookies = None
    if args.input and _is_url(args.input):
        source_url = args.input
        cookies = _session_cookies()
        html = fetch_html(source_url, cookies)
        fallback_name = str(_url_stem(source_url))
    elif args.input:
        in_path = Path(args.input)
        if not in_path.is_file():
            print(f"error: input file not found: {args.input}", file=sys.stderr)
            return 2
        html = in_path.read_text(encoding="utf-8")
        fallback_name = in_path.stem
    else:
        html = sys.stdin.read()
        fallback_name = "lesson"

    if not html.strip():
        print("error: empty input", file=sys.stderr)
        return 2

    steps = extract_steps(html)
    if not steps:
        print("warning: no lesson steps found in input", file=sys.stderr)

    title = extract_title(html)
    name = slugify(title) if title else fallback_name

    if args.format == "json":
        text, ext = to_json(steps), ".json"
    else:
        text, ext = to_markdown(steps, title), ".md"

    # Default layout: <out-dir>/<name>/<name>.<ext> with images alongside.
    if args.output:
        out_path = Path(args.output) / "output"
    else:
        out_path = Path(args.out_dir) / "output" / name / f"{name}{ext}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Download lesson images into the same directory and rewrite references.
    if source_url and not args.no_images:
        srcs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
        if srcs:
            img_dir = out_path.parent
            img_dir.mkdir(parents=True, exist_ok=True)
            mapping = download_images(srcs, source_url, img_dir, cookies)
            for src, fname in mapping.items():
                text = text.replace(f"]({src})", f"]({fname})")
            print(f"downloaded {len(mapping)} image(s) -> {img_dir}",
                  file=sys.stderr)

    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {len(steps)} steps -> {out_path}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
