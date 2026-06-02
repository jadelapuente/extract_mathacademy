"""Regression tests for extract_mathacademy.

Run with:  pytest
"""
import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import extract_mathacademy as ex

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_HTML = REPO_ROOT / "test.html"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def mathml(snippet: str):
    """Parse a MathML <math> snippet and return the <math> tag."""
    soup = BeautifulSoup(snippet, "html.parser")
    return soup.find("math")


def m2l(snippet: str) -> str:
    return ex.normalize_latex(ex.mathml_to_latex(mathml(snippet)))


def make_span(title_inner: str, block: bool = False):
    """Build a mjpage span wrapping an SVG whose <title> holds title_inner."""
    cls = "mjpage mjpage__block" if block else "mjpage"
    html = (
        f'<span class="{cls}"><svg><title>{title_inner}</title>'
        f"<path/></svg></span>"
    )
    return BeautifulSoup(html, "html.parser").find("span")


# --------------------------------------------------------------------------- #
# MathML -> LaTeX unit tests                                                  #
# --------------------------------------------------------------------------- #

def test_msup():
    assert m2l("<math><msup><mi>x</mi><mn>2</mn></msup></math>") == "x^{2}"


def test_msub():
    assert m2l("<math><msub><mi>a</mi><mn>1</mn></msub></math>") == "a_{1}"


def test_msup_wraps_multichar_base():
    out = m2l("<math><msup><mrow><mi>x</mi><mi>y</mi></mrow><mn>2</mn></msup></math>")
    assert out == "{xy}^{2}"


def test_mfrac():
    out = m2l("<math><mfrac><mn>1</mn><mn>2</mn></mfrac></math>")
    assert out == "\\frac{1}{2}"


def test_msqrt():
    assert m2l("<math><msqrt><mn>2</mn></msqrt></math>") == "\\sqrt{2}"


def test_mroot():
    out = m2l("<math><mroot><mn>8</mn><mn>3</mn></mroot></math>")
    assert out == "\\sqrt[3]{8}"


def test_operator_mapping():
    # U+2212 minus, U+22C5 dot operator
    out = m2l("<math><mn>2</mn><mo>−</mo><mn>1</mn></math>")
    assert out == "2-1"
    out = m2l("<math><mn>2</mn><mo>⋅</mo><mn>3</mn></math>")
    assert out == "2 \\cdot 3"


def test_mtable_becomes_aligned():
    snippet = (
        "<math><mtable>"
        "<mtr><mtd><mi>a</mi></mtd><mtd><mn>1</mn></mtd></mtr>"
        "<mtr><mtd><mi>b</mi></mtd><mtd><mn>2</mn></mtd></mtr>"
        "</mtable></math>"
    )
    out = m2l(snippet)
    assert out == "\\begin{aligned} a & 1 \\\\ b & 2 \\end{aligned}"


def test_delimiters_open_close():
    snippet = (
        '<math><mo data-mjx-texclass="OPEN">(</mo><mi>x</mi>'
        '<mo data-mjx-texclass="CLOSE">)</mo></math>'
    )
    assert m2l(snippet) == "\\left(x\\right)"


# --------------------------------------------------------------------------- #
# normalize_latex                                                             #
# --------------------------------------------------------------------------- #

def test_normalize_collapses_whitespace():
    assert ex.normalize_latex("a^{2}\n  -\n  b") == "a^{2} - b"


def test_clean_inline_single_line():
    assert ex.clean_inline("Factoring a Sum of\n  Squares") == "Factoring a Sum of Squares"


# --------------------------------------------------------------------------- #
# mjpage span handling (v2 vs v3, inline vs block)                            #
# --------------------------------------------------------------------------- #

def test_mjpage_v3_mathml_inline():
    span = make_span("<math><msup><mi>x</mi><mn>2</mn></msup></math>")
    assert ex.mjpage_to_latex(span) == "$x^{2}$"


def test_mjpage_v3_block():
    span = make_span("<math><msup><mi>x</mi><mn>2</mn></msup></math>", block=True)
    assert ex.mjpage_to_latex(span) == "\n$$ x^{2} $$\n"


def test_mjpage_v2_raw_latex_is_normalized():
    span = make_span("\n      a^2 - b^2 = (a+b)(a-b).\n    ")
    assert ex.mjpage_to_latex(span) == "$a^2 - b^2 = (a+b)(a-b).$"


def test_mjpage_missing_svg_is_empty():
    span = BeautifulSoup('<span class="mjpage"></span>', "html.parser").find("span")
    assert ex.mjpage_to_latex(span) == ""


# --------------------------------------------------------------------------- #
# End-to-end against the real fixture                                         #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def steps():
    return ex.extract_steps(TEST_HTML.read_text(encoding="utf-8"))


def test_step_count_and_types(steps):
    assert len(steps) == 5
    assert steps[0]["type"] == "tutorial"
    assert [s["type"] for s in steps[1:]] == ["example"] * 4


def test_titles_are_single_line(steps):
    for s in steps:
        assert "\n" not in s["title"]
    assert steps[1]["title"] == "Factoring a Sum of Squares"


def test_tutorial_has_body_examples_have_qa(steps):
    assert "body" in steps[0] and steps[0]["body"]
    for s in steps[1:]:
        assert s["question"]
        assert s["explanation"]


def test_no_newlines_inside_block_math(steps):
    """The core regression guard: block formulas must stay on one line."""
    md = ex.to_markdown(steps)
    for formula in re.findall(r"\$\$(.+?)\$\$", md, flags=re.DOTALL):
        assert "\n" not in formula, f"newline leaked into math: {formula!r}"


def test_markdown_starts_with_first_step(steps):
    md = ex.to_markdown(steps)
    assert md.startswith("## [tutorial] Introduction")


def test_json_is_a_bare_step_array(steps):
    doc = json.loads(ex.to_json(steps))
    assert isinstance(doc, list)
    assert len(doc) == 5
    assert doc[0]["id"] == "20991"


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def test_cli_writes_markdown_file(tmp_path):
    src = tmp_path / "lesson.html"
    src.write_text(TEST_HTML.read_text(encoding="utf-8"), encoding="utf-8")
    rc = ex.main([str(src)])
    assert rc == 0
    assert (tmp_path / "lesson.md").is_file()


def test_cli_writes_json_file(tmp_path):
    src = tmp_path / "lesson.html"
    src.write_text(TEST_HTML.read_text(encoding="utf-8"), encoding="utf-8")
    rc = ex.main([str(src), "--format", "json"])
    assert rc == 0
    assert (tmp_path / "lesson.json").is_file()


def test_cli_missing_file_returns_2(tmp_path):
    assert ex.main([str(tmp_path / "nope.html")]) == 2
