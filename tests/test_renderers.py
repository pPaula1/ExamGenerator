from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RENDERERS_DIR = PROJECT_ROOT / "tools" / "renderers"
if str(RENDERERS_DIR) not in sys.path:
    sys.path.insert(0, str(RENDERERS_DIR))

from exam_pdf_renderer import load_exam_tasks, load_json, resolve_ref  # noqa: E402
from schema_utils import validate_instance  # noqa: E402
from workspace_renderer import render_workspace_blocks  # noqa: E402


class RendererTests(unittest.TestCase):
    def test_resolve_ref_supports_data_tasks(self) -> None:
        exam_file = (PROJECT_ROOT / "data" / "exams" / "exam_all_tasks_example.json").resolve()
        resolved = resolve_ref(exam_file, "../tasks/A1/2025_mii_ht_A1/2025_mii_ht_A1.json")
        self.assertTrue(resolved.exists(), f"Resolved path should exist: {resolved}")
        self.assertIn(str((PROJECT_ROOT / "data" / "tasks").resolve()), str(resolved))

    def test_workspace_centering_differs_by_list_context(self) -> None:
        blocks = [{"type": "grid", "height_cm": 2, "grid": "karo_5mm"}]
        normal = render_workspace_blocks(blocks, str, in_list_item=False)
        in_list = render_workspace_blocks(blocks, str, in_list_item=True)
        self.assertNotIn(r"\hspace*{-\leftmargin}", normal)
        self.assertIn(r"\hspace*{-\leftmargin}", in_list)

    def test_exam_and_task_schema_validation(self) -> None:
        exam = load_json((PROJECT_ROOT / "data" / "exams" / "exam_all_tasks_example.json").resolve())
        validate_instance(exam, "exam", label="exam_fixture")

        task = load_json(
            (PROJECT_ROOT / "data" / "tasks" / "A1" / "2025_mii_ht_A1" / "2025_mii_ht_A1.json").resolve()
        )
        validate_instance(task, "task", label="task_fixture")

    def test_soft_page_break_flag_is_set_between_tasks(self) -> None:
        exam_file = (PROJECT_ROOT / "data" / "exams" / "exam_all_tasks_example.json").resolve()
        exam_data = json.loads(exam_file.read_text(encoding="utf-8"))
        exam_data.setdefault("render", {})
        exam_data["render"]["page_break_between_tasks"] = True
        exam_data["render"]["min_remaining_for_next_task"] = 0.30

        tasks = load_exam_tasks(exam_file, exam_data)
        self.assertGreaterEqual(len(tasks), 2)
        second_render = tasks[1]["task"].get("render") or {}
        self.assertIn("soft_page_break_before", second_render)
        self.assertAlmostEqual(float(second_render["soft_page_break_before"]), 0.30, places=2)


if __name__ == "__main__":
    unittest.main()
