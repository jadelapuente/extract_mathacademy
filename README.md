# extract_mathacademy

A script to extract Math Academy lesson content from HTML into clean Markdown or
JSON for easier and cheaper LLM parsing.

It strips presentational markup and recovers the LaTeX source of every formula
from the MathJax SVG `<title>` (both MathJax v2 raw-LaTeX and v3 MathML output),
emitting compact single-line LaTeX that is cheap for an LLM to read.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python extract_mathacademy.py lesson.html                # writes lesson/lesson.md
python extract_mathacademy.py lesson.html --format json  # writes lesson/lesson.json
python extract_mathacademy.py lesson.html -o out.md      # explicit output path
cat lesson.html | python extract_mathacademy.py          # stdin -> lesson/lesson.md
```

To extract every Math Academy lesson topic completed within an inclusive date
range, stay logged in to Math Academy in your browser and run:

```bash
python extract_mathacademy.py \
  --start 2026-06-01 \
  --end 2026-08-01
```

This creates `2026-06-01-to-2026-08-01/`, writes `topic_ids.json` and
`manifest.json`, then stores each topic in its own regular per-lesson
subdirectory. Dates must be ISO `YYYY-MM-DD`. By default only completed Lesson
task topics are included; pass `--include-review-topics` to include Review task
topics too.

By default output is written to a per-lesson directory under the current working
directory, or under `--out-dir` when provided. For URL input, downloaded images
are written next to the generated output file and Markdown image references are
rewritten to those local filenames. JSON is a bare array of step objects; each
step has `id`, `type`, `title`, and either `body` (tutorials) or `question` +
`explanation` (examples).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover the MathML→LaTeX conversion, whitespace normalization, the v2/v3 and
inline/block span paths, end-to-end extraction against `test.html`, and the CLI.
