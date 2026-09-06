#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent / "src"
__path__ = [str(_SRC_DIR / "extract_mathacademy")]
sys.path.insert(0, str(_SRC_DIR))

from extract_mathacademy.cli.extract_lesson import main


if __name__ == "__main__":
    raise SystemExit(main())
