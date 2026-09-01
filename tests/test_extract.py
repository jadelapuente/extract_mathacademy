"""Regression tests for extract_mathacademy.

Run with:  pytest
"""
import json
import re
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import extract_mathacademy as ex
from _completed import CompletedTopicRecord
from _grouping import group_completed_topics

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_HTML = REPO_ROOT / "test.html"
TEST_HTML_MARKDOWN_SHA256 = (
    "297c9ef8e27a0d1895b5dd847e31676ded7bf3a72ad8dbec4cce0fa77fcd2c35"
)
TEST_HTML_JSON_SHA256 = (
    "9604269445a5b26eae3cb38e26be272f35dc7203f17c19c055378f2b94254c94"
)


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


def test_test_html_output_hashes_are_stable(steps):
    markdown = ex.to_markdown(steps)
    json_text = ex.to_json(steps)

    assert (
        sha256(markdown.encode("utf-8")).hexdigest()
        == TEST_HTML_MARKDOWN_SHA256
    )
    assert (
        sha256(json_text.encode("utf-8")).hexdigest()
        == TEST_HTML_JSON_SHA256
    )


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


def test_completed_topic_records_preserve_relationship_metadata(monkeypatch):
    def fake_fetch_previous_tasks(before, cookies=None):
        return [
            {
                "id": 1,
                "type": "Lesson",
                "completed": "2026-07-05T11:16:14.000Z",
                "nodeId": 101,
                "nextNodeId": 102,
                "topic": {"id": 10, "name": "Conditional Statements"},
            },
            {
                "id": 2,
                "type": "Lesson",
                "completed": "2026-07-05T10:48:24.000Z",
                "learningNode": {"id": 102, "previous": {"id": 101}},
                "topic": {"id": 20, "name": "Biconditional Statements"},
            },
        ]

    monkeypatch.setattr(ex, "fetch_previous_tasks", fake_fetch_previous_tasks)

    records = ex.completed_topic_records(
        date(2026, 6, 1),
        date(2026, 8, 1),
        cookies=[],
    )

    assert [record.topic_id for record in records] == [10, 20]
    assert records[0].topic_name == "Conditional Statements"
    assert records[0].learning_node_id == 101
    assert records[0].next_learning_node_id == 102
    assert records[1].learning_node_id == 102
    assert records[1].previous_learning_node_id == 101


def completed_record(
    topic_id,
    topic_name,
    node_id=None,
    previous_node_id=None,
    next_node_id=None,
    prerequisite_topic_ids=(),
):
    return CompletedTopicRecord(
        task_id=topic_id,
        task_type="Lesson",
        topic_id=topic_id,
        topic_name=topic_name,
        completed_at=datetime(
            2026,
            7,
            1,
            minute=topic_id % 60,
            tzinfo=timezone.utc,
        ),
        learning_node_id=node_id,
        previous_learning_node_id=previous_node_id,
        next_learning_node_id=next_node_id,
        prerequisite_topic_ids=tuple(prerequisite_topic_ids),
    )


def test_group_completed_topics_orders_disconnected_node_chains():
    records = [
        completed_record(2, "Biconditional Statements", 2, 1, 3),
        completed_record(1, "Conditional Statements", 1, None, 2),
        completed_record(3, "Truth Tables", 3, 2, None),
        completed_record(5, "Cotangent Equations", 5, 4, None),
        completed_record(4, "Secant Equations", 4, None, 5),
    ]

    def namer(group_records):
        if group_records[0].topic_id == 1:
            return "Logic and Sets"
        return "Trig Equations"

    groups = group_completed_topics(records, namer=namer)

    assert [group.slug for group in groups] == [
        "logic-and-sets",
        "trig-equations",
    ]
    assert [[record.topic_id for record in group.records] for group in groups] == [
        [1, 2, 3],
        [4, 5],
    ]
    assert not any(group.slug.startswith("group-") for group in groups)


def test_group_completed_topics_resolves_slug_collisions_without_group_prefix():
    records = [
        completed_record(1, "Topic A"),
        completed_record(2, "Topic B"),
    ]

    groups = group_completed_topics(records, namer=lambda records: "Same Name")

    assert [group.slug for group in groups] == ["same-name", "same-name-2"]
    assert not any(group.slug.startswith("group-") for group in groups)


def test_extract_prerequisite_topic_ids_from_topic_html():
    html = """
    <div id="prerequisites">
      <a href="/topics/conditional-statements-246" class="prerequisiteLink">
        Conditional Statements
      </a>
      <a href="/topics/247" class="prerequisiteLink">
        Logical Equivalence
      </a>
    </div>
    """

    assert ex.extract_prerequisite_topic_ids(html) == [246, 247]


def test_group_completed_topics_uses_prerequisite_topic_edges():
    records = [
        completed_record(248, "Biconditional Statements", prerequisite_topic_ids=[246]),
        completed_record(246, "Conditional Statements"),
        completed_record(247, "Logical Equivalence"),
    ]

    groups = group_completed_topics(records)

    assert [[record.topic_id for record in group.records] for group in groups] == [
        [246, 248],
        [247],
    ]


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


def topic_html_with_prereqs(topic_id, *prereq_ids):
    prereqs = "\n".join(
        f"""
        <div class="prerequisite">
          <a href="/topics/prereq-{prereq_id}" class="prerequisiteLink">
            Topic {prereq_id}
          </a>
        </div>
        """
        for prereq_id in prereq_ids
    )
    return f"""
    <html>
      <body>
        <div id="topicName">Topic {topic_id}</div>
        <div id="prerequisites">{prereqs}</div>
        <div class="step" stepid="1" steptype="tutorial">
          <div class="stepName"><a class="stepAnchor">Introduction</a></div>
          <p>Body for topic {topic_id}</p>
        </div>
      </body>
    </html>
    """


def test_start_end_cli_extracts_grouped_completed_topic_artifacts(
    monkeypatch,
    tmp_path,
    capsys,
):
    records = [
        completed_record(477, "Conditional Statements"),
        completed_record(478, "Biconditional Statements"),
        completed_record(1016, "Parametric Curves"),
    ]
    monkeypatch.setattr(ex, "_session_cookies", lambda: [])
    monkeypatch.setattr(ex, "completed_topic_records", lambda *a, **kw: records)

    html_by_id = {
        "477": topic_html_with_prereqs(477),
        "478": topic_html_with_prereqs(478, 477),
        "1016": topic_html_with_prereqs(1016),
    }
    monkeypatch.setattr(
        ex,
        "fetch_html",
        lambda url, cookies=None: html_by_id[url.rstrip("/").split("/")[-1]],
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
    assert json.loads((range_dir / "topic_ids.json").read_text()) == [
        477,
        478,
        1016,
    ]
    groups = json.loads((range_dir / "groups.json").read_text())
    assert groups["schema_version"] == 1
    assert groups["grouping"] == "node-chain"
    assert [group["slug"] for group in groups["groups"]] == [
        "conditional-statements",
        "parametric-curves",
    ]
    assert [group["topic_ids"] for group in groups["groups"]] == [
        [477, 478],
        [1016],
    ]
    manifest = json.loads((range_dir / "manifest.json").read_text())
    assert groups["groups"][0]["topics"][1]["prerequisite_topic_ids"] == [477]
    assert manifest[0]["group_slug"] == "conditional-statements"
    assert manifest[0]["output"] == str(
        range_dir
        / "conditional-statements"
        / "topic-477"
        / "topic-477.md"
    )
    assert (
        range_dir
        / "conditional-statements"
        / "topic-478"
        / "topic-478.md"
    ).is_file()
    assert (range_dir / "parametric-curves" / "topic-1016" / "topic-1016.md").is_file()
    assert not any(path.name.startswith("group-") for path in range_dir.iterdir())

    captured = capsys.readouterr()
    assert "wrote 3 completed topic(s)" in captured.err
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


def test_cli_rejects_removed_group_by_option(capsys):
    with pytest.raises(SystemExit) as exc:
        ex.main([
            "--start",
            "2026-06-01",
            "--end",
            "2026-08-01",
            "--group-by",
            "none",
        ])

    assert exc.value.code == 2
    assert "unrecognized arguments: --group-by" in capsys.readouterr().err
