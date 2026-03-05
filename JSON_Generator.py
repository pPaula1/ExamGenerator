#!/usr/bin/env python3
"""Backward-compatible wrapper for moved generator script."""
from pathlib import Path
import runpy
import sys

TARGET = Path(__file__).resolve().parent / "tools" / "generators" / "task_json_builder_gui.py"
if not TARGET.exists():
    raise SystemExit(f"Missing target script: {TARGET}")

sys.path.insert(0, str(TARGET.parent))
runpy.run_path(str(TARGET), run_name="__main__")
