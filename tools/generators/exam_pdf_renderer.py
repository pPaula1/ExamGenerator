#!/usr/bin/env python3
"""Backward-compatible alias. Use ../renderers/task_pdf_renderer.py."""
from pathlib import Path
import runpy
import sys

TARGET = Path(__file__).resolve().parent.parent / "renderers" / "task_pdf_renderer.py"
if not TARGET.exists():
    raise SystemExit(f"Missing target script: {TARGET}")

sys.path.insert(0, str(TARGET.parent))
runpy.run_path(str(TARGET), run_name="__main__")
