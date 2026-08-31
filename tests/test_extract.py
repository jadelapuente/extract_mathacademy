"""Regression tests for extract_mathacademy.

Run with:  pytest
"""
import json
import re
from datetime import date
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


def test_extracted_steps_are_typed_mapping_compatible_objects(steps):
    assert type(steps[0]).__name__ == "TutorialStep"
    assert type(steps[1]).__name__ == "ExampleStep"
    assert steps[0].title == "Introduction"
    assert steps[0]["title"] == steps[0].title
    assert steps[0].get("body") == steps[0].body
    assert dict(steps[1]) == steps[1].to_dict()


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
    rc = ex.main([str(src), "--out-dir", str(tmp_path)])
    assert rc == 0
    # No #topicName in test.html, so the name falls back to the input stem.
    assert (tmp_path / "lesson" / "lesson.md").is_file()


def test_cli_writes_json_file(tmp_path):
    src = tmp_path / "lesson.html"
    src.write_text(TEST_HTML.read_text(encoding="utf-8"), encoding="utf-8")
    rc = ex.main([str(src), "--format", "json", "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "lesson" / "lesson.json").is_file()


def test_cli_explicit_output_path(tmp_path):
    src = tmp_path / "lesson.html"
    src.write_text(TEST_HTML.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "custom.md"
    rc = ex.main([str(src), "-o", str(out)])
    assert rc == 0
    assert out.is_file()


def test_write_extracted_lesson_downloads_images_next_to_output(monkeypatch, tmp_path):
    html = """
    <html>
      <body>
        <div id="topicName">Image Lesson</div>
        <div class="step" stepid="1" steptype="tutorial">
          <div class="stepName"><a class="stepAnchor">Introduction</a></div>
          <p>See <img src="/graphics/hash" alt="diagram"></p>
        </div>
      </body>
    </html>
    """

    def fake_download_images(srcs, base_url, out_dir, cookies):
        assert srcs == ["/graphics/hash"]
        assert base_url == "https://mathacademy.com/topics/1"
        assert cookies == ["session"]
        (out_dir / "hash.png").write_bytes(b"png")
        return {"/graphics/hash": "hash.png"}

    monkeypatch.setattr(ex, "download_images", fake_download_images)

    out_path, step_count = ex.write_extracted_lesson(
        html,
        fallback_name="fallback",
        fmt="markdown",
        out_dir=tmp_path,
        source_url="https://mathacademy.com/topics/1",
        cookies=["session"],
    )

    assert step_count == 1
    assert out_path == tmp_path / "image-lesson" / "image-lesson.md"
    assert (out_path.parent / "hash.png").is_file()
    assert not (out_path.parent / "images").exists()
    assert "![diagram](hash.png)" in out_path.read_text(encoding="utf-8")


def test_cli_missing_file_returns_2(tmp_path):
    assert ex.main([str(tmp_path / "nope.html")]) == 2


# --------------------------------------------------------------------------- #
# Title / slug                                                                #
# --------------------------------------------------------------------------- #

def test_slugify():
    assert ex.slugify("Inverses of Quadratic Functions") == \
        "inverses-of-quadratic-functions"
    assert ex.slugify("  Multi   space & punct!  ") == "multi-space-punct"
    assert ex.slugify("") == "lesson"


def test_extract_title_present():
    html = '<div id="topicName">Inverses of Quadratic Functions</div>'
    assert ex.extract_title(html) == "Inverses of Quadratic Functions"


def test_extract_title_absent():
    assert ex.extract_title(TEST_HTML.read_text(encoding="utf-8")) is None


def test_markdown_includes_title_heading(steps):
    md = ex.to_markdown(steps, title="My Lesson")
    assert md.startswith("# My Lesson\n")
    # Without a title, output is unchanged (no leading H1).
    assert not ex.to_markdown(steps).startswith("# ")


# --------------------------------------------------------------------------- #
# Completed topic ids                                                         #
# --------------------------------------------------------------------------- #

def completed_task(task_id, task_type, topic_id, completed):
    return {
        "id": task_id,
        "type": task_type,
        "completed": completed,
        "topic": {"id": topic_id, "name": f"Topic {topic_id}"},
    }


def test_completed_topic_ids_pages_and_deduplicates(monkeypatch):
    pages = [
        [
            completed_task(1, "Lesson", 10, "2026-07-05T11:16:14.000Z"),
            completed_task(2, "Review", 99, "2026-07-05T10:48:24.000Z"),
            completed_task(3, "Lesson", 10, "2026-06-15T12:00:00.000Z"),
        ],
        [
            completed_task(4, "Lesson", 20, "2026-06-01T07:00:00.000Z"),
            completed_task(5, "Lesson", 30, "2026-06-01T06:59:59.000Z"),
        ],
    ]
    calls = []

    def fake_fetch_previous_tasks(before, cookies=None):
        calls.append(before)
        return pages[len(calls) - 1]

    monkeypatch.setattr(ex, "fetch_previous_tasks", fake_fetch_previous_tasks)

    ids = ex.completed_topic_ids(
        date(2026, 6, 1),
        date(2026, 8, 1),
        cookies=[],
    )

    assert ids == [10, 20]
    assert len(calls) == 2


def test_completed_topic_ids_can_include_review_topics(monkeypatch):
    def fake_fetch_previous_tasks(before, cookies=None):
        return [
            completed_task(1, "Lesson", 10, "2026-07-05T11:16:14.000Z"),
            completed_task(2, "Review", 99, "2026-07-05T10:48:24.000Z"),
            completed_task(3, "Lesson", 20, "2026-06-01T06:59:59.000Z"),
        ]

    monkeypatch.setattr(ex, "fetch_previous_tasks", fake_fetch_previous_tasks)

    ids = ex.completed_topic_ids(
        date(2026, 6, 1),
        date(2026, 8, 1),
        cookies=[],
        include_review_topics=True,
    )

    assert ids == [10, 99]


def topic_html(topic_id):
    return f"""
    <html>
      <body>
        <div id="topicName">Topic {topic_id}</div>
        <div class="step" stepid="1" steptype="tutorial">
          <div class="stepName"><a class="stepAnchor">Introduction</a></div>
          <p>Body for topic {topic_id}</p>
        </div>
      </body>
    </html>
    """


def test_start_end_cli_extracts_completed_topic_artifacts(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setattr(ex, "_session_cookies", lambda: [])
    monkeypatch.setattr(ex, "completed_topic_ids", lambda *a, **kw: [477, 1016])
    monkeypatch.setattr(
        ex,
        "fetch_html",
        lambda url, cookies=None: topic_html(url.rstrip("/").split("/")[-1]),
    )

    rc = ex.main([
        "--start",
        "2026-06-01",
        "--end",
        "2026-08-01",
        "--out-dir",
        str(tmp_path),
        "--no-images",
    ])

    assert rc == 0
    range_dir = tmp_path / "2026-06-01-to-2026-08-01"
    assert json.loads((range_dir / "topic_ids.json").read_text()) == [477, 1016]
    assert json.loads((range_dir / "manifest.json").read_text()) == [
        {
            "topic_id": 477,
            "url": "https://mathacademy.com/topics/477",
            "output": str(range_dir / "topic-477" / "topic-477.md"),
            "steps": 1,
        },
        {
            "topic_id": 1016,
            "url": "https://mathacademy.com/topics/1016",
            "output": str(range_dir / "topic-1016" / "topic-1016.md"),
            "steps": 1,
        },
    ]
    assert (range_dir / "topic-477" / "topic-477.md").read_text().startswith(
        "# Topic 477\n"
    )
    assert (range_dir / "topic-1016" / "topic-1016.md").is_file()

    captured = capsys.readouterr()
    assert "wrote 2 completed topic(s)" in captured.err
    assert captured.out == ""


def test_start_end_cli_rejects_output_file(tmp_path, capsys):
    rc = ex.main([
        "--start",
        "2026-06-01",
        "--end",
        "2026-08-01",
        "-o",
        str(tmp_path / "topic_ids.json"),
    ])

    assert rc == 2
    assert "use --out-dir" in capsys.readouterr().err


def test_start_end_cli_requires_both_dates(capsys):
    rc = ex.main(["--start", "2026-06-01"])

    assert rc == 2
    assert "--start and --end" in capsys.readouterr().err
