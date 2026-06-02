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
python extract_mathacademy.py lesson.html                # writes lesson.md
python extract_mathacademy.py lesson.html --format json  # writes lesson.json
python extract_mathacademy.py lesson.html -o out.md      # explicit output path
cat lesson.html | python extract_mathacademy.py          # stdin -> lesson.md
```

By default output is written to a file next to the input. JSON is a bare array
of step objects; each step has `id`, `type`, `title`, and either `body`
(tutorials) or `question` + `explanation` (examples).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover the MathML→LaTeX conversion, whitespace normalization, the v2/v3 and
inline/block span paths, end-to-end extraction against `test.html`, and the CLI.
