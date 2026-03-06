#!/usr/bin/env python3
"""
Render a complete exam JSON to one LaTeX/PDF document.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from header_pdf_renderer import build_header_block_tex, load_json as load_header_json
from schema_utils import validate_instance
from task_pdf_renderer import latex_escape, render_task


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_font_family(exam_data: dict[str, Any]) -> str:
    render_cfg = exam_data.get("render") or {}
    raw = str(render_cfg.get("font_family", "times")).strip().lower()
    aliases = {
        "latin_modern": "latin-modern",
    }
    value = aliases.get(raw, raw)
    if value not in {"default", "latin-modern", "times"}:
        return "times"
    return value


def font_package_lines(font_family: str) -> list[str]:
    if font_family == "latin-modern":
        return [r"\usepackage{lmodern}"]
    if font_family == "times":
        return [
            r"\usepackage{newtxtext}",
            r"\usepackage{newtxmath}",
        ]
    return []


def resolve_ref(base_file: Path, ref: str) -> Path:
    p = Path(str(ref).strip())
    if p.is_absolute():
        return p

    candidates = [
        (base_file.parent / p).resolve(),
        (PROJECT_ROOT / p).resolve(),
        (PROJECT_ROOT / "data" / p).resolve(),
    ]

    parts = list(p.parts)
    if "tasks" in parts:
        idx = parts.index("tasks")
        candidates.append((PROJECT_ROOT / Path(*parts[idx:])).resolve())
        candidates.append((PROJECT_ROOT / "data" / Path(*parts[idx:])).resolve())
    if str(p).startswith("../tasks/"):
        candidates.append((PROJECT_ROOT / "tasks" / str(p)[9:]).resolve())
        candidates.append((PROJECT_ROOT / "data" / "tasks" / str(p)[9:]).resolve())
    if str(p).startswith("tasks/"):
        candidates.append((PROJECT_ROOT / p).resolve())
        candidates.append((PROJECT_ROOT / "data" / p).resolve())

    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def merge_school_into_header(
    exam_file: Path,
    header_data: dict[str, Any],
    school_ref: str | None,
) -> dict[str, Any]:
    merged = dict(header_data)
    school_data: dict[str, Any] | None = None

    if school_ref:
        school_file = resolve_ref(exam_file, school_ref)
        if school_file.exists():
            school_data = load_json(school_file)
            validate_instance(school_data, "school", label=str(school_file))
            if not merged.get("school_name") and school_data.get("name"):
                merged["school_name"] = school_data.get("name")
            defaults = school_data.get("defaults") or {}
            for key in ("subject", "class_name", "teacher"):
                if not merged.get(key) and defaults.get(key):
                    merged[key] = defaults.get(key)
            if not merged.get("logo_path"):
                logo = school_data.get("logo") or {}
                logo_rel = str(logo.get("path", "")).strip()
                if logo_rel:
                    merged["logo_path"] = str((school_file.parent / logo_rel).resolve())

    return merged


def task_points(task: dict[str, Any]) -> float:
    if task.get("points") is not None:
        try:
            return float(task.get("points"))
        except Exception:
            pass
    total = 0.0
    for p in task.get("parts") or []:
        try:
            total += float(p.get("points", 0))
        except Exception:
            continue
    return total


def load_exam_tasks(exam_file: Path, exam_data: dict[str, Any]) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    page_break_between = bool((exam_data.get("render") or {}).get("page_break_between_tasks", False))
    min_remaining_for_next = float((exam_data.get("render") or {}).get("min_remaining_for_next_task", 0.30))
    min_remaining_for_next = max(0.05, min(0.95, min_remaining_for_next))
    entries = exam_data.get("tasks") or []

    for idx, entry in enumerate(entries):
        if isinstance(entry, str):
            path_ref = entry
            task_id = None
            points_override = None
            page_break_before = False
        else:
            path_ref = str(entry.get("path", ""))
            task_id = entry.get("task_id")
            points_override = entry.get("points_override")
            page_break_before = bool(entry.get("page_break_before", False))

        task_file = resolve_ref(exam_file, path_ref)
        if not task_file.exists():
            raise FileNotFoundError(f"Task JSON not found: {path_ref} -> {task_file}")
        data = load_json(task_file)
        validate_instance(data, "task", label=str(task_file))

        if task_id and str(data.get("id", "")) != str(task_id):
            raise ValueError(f"task_id mismatch in {task_file}: expected '{task_id}', got '{data.get('id')}'")

        points = float(points_override) if points_override is not None else task_points(data)

        task_render = dict(data.get("render") or {})
        if idx > 0 and page_break_between:
            task_render["soft_page_break_before"] = min_remaining_for_next
        if page_break_before:
            task_render["page_break_before"] = True
        data = dict(data)
        data["render"] = task_render

        loaded.append(
            {
                "file": task_file,
                "task": data,
                "points": points,
            }
        )
    return loaded


def render_points_overview(rows: list[dict[str, Any]]) -> str:
    # Keep heading + table together; if there is not enough space,
    # LaTeX moves the whole block to the next page.
    needed_lines = len(rows) + 8
    lines = [
        rf"\Needspace{{{needed_lines}\baselineskip}}",
        r"\section*{Punkteuebersicht}",
        r"\begin{tabular}{|p{0.10\linewidth}|p{0.68\linewidth}|p{0.16\linewidth}|}",
        r"\hline",
        r"\textbf{Nr.} & \textbf{Aufgabe} & \textbf{Punkte} \\",
        r"\hline",
    ]
    total = 0.0
    for i, row in enumerate(rows, start=1):
        name = latex_escape(str(row["task"].get("name", row["task"].get("id", f"Task {i}"))))
        pts = float(row["points"])
        total += pts
        pts_text = f"{pts:g}"
        pts_cell = rf"\hfill / {pts_text}"
        lines.extend(
            [
                rf"{i} & {name} & {pts_cell} \\",
                r"\hline",
            ]
        )
    lines.extend(
        [
            rf"\multicolumn{{2}}{{|r|}}{{\textbf{{Gesamt}}}} & \textbf{{\hfill / {total:g}}} \\",
            r"\hline",
            r"\end{tabular}",
        ]
    )
    return "\n".join(lines)


def build_exam_tex(
    exam_file: Path,
    exam_data: dict[str, Any],
    out_dir: Path,
) -> str:
    header_file, header_data, tasks, total_points = prepare_exam_parts(exam_file, exam_data)
    font_family = normalize_font_family(exam_data)
    font_lines = font_package_lines(font_family)
    # newtxmath/newtxtext ("times") conflicts with amssymb on \Bbbk.
    # Keep amsmath everywhere, but skip amssymb for the times preset.
    symbol_lines = [] if font_family == "times" else [r"\usepackage{amssymb}"]

    header_block = build_header_block_tex(header_file, header_data, f"{total_points:g}")

    body: list[str] = [header_block, r"\vspace{0.8cm}"]
    for item in tasks:
        body.append(render_task(item["file"], item["task"], out_dir))
        body.append(r"\vspace{1em}")
        body.append(r"\hrule")
        body.append(r"\vspace{1em}")

    body.append(render_points_overview(tasks))

    return "\n".join(
        [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[ngerman]{babel}",
            r"\usepackage{amsmath}",
            *font_lines,
            *symbol_lines,
            r"\usepackage{geometry}",
            r"\usepackage{graphicx}",
            r"\usepackage{array}",
            r"\usepackage{needspace}",
            r"\usepackage{enumitem}",
            r"\usepackage{parskip}",
            r"\usepackage{tikz}",
            r"\geometry{margin=2cm}",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\tabcolsep}{6pt}",
            r"\renewcommand{\arraystretch}{1.0}",
            r"\newcommand{\cb}{\raisebox{0pt}[0.85em][0pt]{\fbox{\rule{0pt}{0.7em}\rule{0.7em}{0pt}}}}",
            r"\begin{document}",
            *body,
            r"\end{document}",
            "",
        ]
    )


def prepare_exam_parts(
    exam_file: Path,
    exam_data: dict[str, Any],
) -> tuple[Path, dict[str, Any], list[dict[str, Any]], float]:
    header_spec = exam_data.get("header")
    if isinstance(header_spec, str):
        header_file = resolve_ref(exam_file, header_spec)
        if not header_file.exists():
            raise FileNotFoundError(f"Header JSON not found: {header_spec} -> {header_file}")
        header_data = load_header_json(header_file)
        validate_instance(header_data, "header", label=str(header_file))
    elif isinstance(header_spec, dict):
        header_file = exam_file
        header_data = dict(header_spec)
        validate_instance(header_data, "header", label=f"{exam_file}#header")
    else:
        header_file = exam_file
        header_data = {"title": str(exam_data.get("name", "Pruefung"))}

    header_data = merge_school_into_header(exam_file, header_data, exam_data.get("school_info_ref"))
    tasks = load_exam_tasks(exam_file, exam_data)
    total_points = sum(float(t["points"]) for t in tasks)

    if not header_data.get("title"):
        header_data["title"] = str(exam_data.get("name", "Pruefung"))
    if not header_data.get("subtitle") and exam_data.get("subtitle"):
        header_data["subtitle"] = str(exam_data.get("subtitle"))

    return header_file, header_data, tasks, total_points


def compile_pdf(tex_file: Path, out_dir: Path) -> None:
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        print("pdflatex not found. Skipping PDF compile.")
        print(f"LaTeX file written: {tex_file}")
        return
    cmd = [
        pdflatex,
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={out_dir}",
        str(tex_file),
    ]
    subprocess.run(cmd, check=True)
    subprocess.run(cmd, check=True)
    print(f"PDF created: {out_dir / (tex_file.stem + '.pdf')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Exam JSON file")
    ap.add_argument("--output-dir", default="out_pdf", help="Output directory for tex/pdf")
    ap.add_argument("--name", default="exam", help="Base name for generated tex/pdf")
    ap.add_argument("--no-compile", action="store_true", help="Only generate .tex, do not run pdflatex")
    args = ap.parse_args()

    exam_file = Path(args.input).resolve()
    if not exam_file.exists():
        raise FileNotFoundError(f"Exam JSON not found: {exam_file}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    exam_data = load_json(exam_file)
    validate_instance(exam_data, "exam", label=str(exam_file))
    tex_content = build_exam_tex(exam_file, exam_data, out_dir)
    tex_file = out_dir / f"{args.name}.tex"
    tex_file.write_text(tex_content, encoding="utf-8")
    print(f"LaTeX written: {tex_file}")

    if not args.no_compile:
        compile_pdf(tex_file, out_dir)


if __name__ == "__main__":
    main()
