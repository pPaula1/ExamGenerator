#!/usr/bin/env python3
"""
json_to_pdf.py

Simple converter:
- reads task JSON files (single file or directory)
- writes one LaTeX document
- optionally compiles PDF via pdflatex
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from workspace_renderer import render_workspace_blocks


def latex_escape(text: str) -> str:
    """Escape plain text while keeping inline LaTeX math ($...$) intact."""
    unicode_map = {
        "−": "-",
        "–": "-",
        "—": "-",
        "·": "*",
        "•": "*",
        "×": "x",
        "÷": "/",
        "∈": " in ",
        "∉": " not in ",
        "ℝ": "R",
        "ℤ": "Z",
        "ℕ": "N",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        "≈": "~",
        "∠": "Winkel ",
        "∥": "||",
        "²": "^2",
        "³": "^3",
        "½": "1/2",
        "¼": "1/4",
        "¾": "3/4",
        "π": "pi",
        "√": "sqrt",
        "→": "->",
        "↔": "<->",
        "„": '"',
        "“": '"',
        "”": '"',
        "‚": "'",
        "‘": "'",
        "’": "'",
        "…": "...",
        "□": "[ ]",
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
        "⁰": "0",
        "¹": "1",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
        "⁺": "+",
        "₊": "+",
        "⁻": "-",
        "₋": "-",
    }
    for old, new in unicode_map.items():
        text = text.replace(old, new)

    # Keep pdflatex-safe character range after normalization.
    text = "".join(ch if ord(ch) <= 255 else " " for ch in text)

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }

    # Preserve inline math regions ($...$) so subscripts/superscripts work.
    out: list[str] = []
    in_math = False
    for i, ch in enumerate(text):
        if ch == "$" and (i == 0 or text[i - 1] != "\\"):
            in_math = not in_math
            out.append("$")
            continue
        if in_math:
            out.append(ch)
        else:
            out.append(replacements.get(ch, ch))
    return "".join(out)


def read_tasks(input_path: Path) -> list[tuple[Path, dict[str, Any]]]:
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        # Load JSON files recursively so passing a top-level tasks folder works.
        files = sorted(input_path.rglob("*.json"))
    else:
        raise FileNotFoundError(f"Input not found: {input_path}")

    if not files:
        raise FileNotFoundError(f"No JSON files found in: {input_path}")

    tasks: list[tuple[Path, dict[str, Any]]] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        tasks.append((f, data))
    return tasks


def render_asset_include(task_file: Path, out_dir: Path, asset: dict[str, Any]) -> str:
    path = asset.get("path", "").strip()
    if not path:
        return ""

    # Path is interpreted relative to the JSON file location.
    # Fallback: parent folder of the JSON folder (common layout: tasks/<set>/tasks + tasks/<set>/assets).
    img_abs = (task_file.parent / path).resolve()
    if not img_abs.exists():
        img_abs = (task_file.parent.parent / path).resolve()
    if not img_abs.exists():
        return rf"\textit{{Bilddatei nicht gefunden: {latex_escape(path)}}}"

    rel_to_tex = Path(
        str(img_abs.relative_to(out_dir)) if str(img_abs).startswith(str(out_dir)) else str(img_abs)
    )
    rel_tex = str(rel_to_tex).replace("\\", "/")
    width = asset.get("width", "0.8\\linewidth")
    caption = asset.get("caption")

    lines = [rf"\includegraphics[width={width}]{{{rel_tex}}}"]
    if caption:
        lines.append(rf"\par\small {latex_escape(str(caption))}")
    return "\n".join(lines)


def render_assets_block(task_file: Path, out_dir: Path, assets: list[dict[str, Any]]) -> str:
    if not assets:
        return ""

    below_assets = [
        a for a in assets
        if a.get("placement", "below_statement") in ("below_statement", "below_part_text", "inline")
    ]
    right_assets = [a for a in assets if a.get("placement") == "right_of_statement"]

    blocks: list[str] = []

    if right_assets:
        right_snippets = []
        for a in right_assets:
            right_snippets.append(render_asset_include(task_file, out_dir, a))
            right_snippets.append(r"\vspace{0.5em}")
        right_joined = "\n".join(right_snippets)
        blocks.append(
            r"\begin{minipage}[t]{0.62\linewidth}" + "\n" +
            r"\vspace{0pt}\textit{(siehe Aufgabenstellung)}" + "\n" +
            r"\end{minipage}\hfill" + "\n" +
            r"\begin{minipage}[t]{0.35\linewidth}" + "\n" +
            r"\vspace{0pt}" + "\n" + right_joined + "\n" +
            r"\end{minipage}"
        )

    full_assets = [a for a in below_assets if a.get("column", "full") == "full"]
    left_assets = [a for a in below_assets if a.get("column") == "left"]
    right_col_assets = [a for a in below_assets if a.get("column") == "right"]

    for a in full_assets:
        inc = render_asset_include(task_file, out_dir, a)
        if inc:
            blocks.append(r"\begin{center}" + "\n" + inc + "\n" + r"\end{center}")

    if left_assets or right_col_assets:
        max_len = max(len(left_assets), len(right_col_assets))
        for i in range(max_len):
            left_inc = render_asset_include(task_file, out_dir, left_assets[i]) if i < len(left_assets) else ""
            right_inc = render_asset_include(task_file, out_dir, right_col_assets[i]) if i < len(right_col_assets) else ""
            blocks.append(
                r"\begin{minipage}[t]{0.48\linewidth}" + "\n" +
                (left_inc or "") + "\n" +
                r"\end{minipage}\hfill" + "\n" +
                r"\begin{minipage}[t]{0.48\linewidth}" + "\n" +
                (right_inc or "") + "\n" +
                r"\end{minipage}" + "\n" +
                r"\vspace{0.5em}"
            )

    return "\n\n".join(blocks)


def render_task(task_file: Path, task: dict[str, Any], out_dir: Path) -> str:
    tid = str(task.get("id", "task"))
    name = latex_escape(str(task.get("name", tid)))
    points = task.get("points", 0)
    statement = latex_escape(str(task.get("statement", "")))
    topic = latex_escape(str(task.get("topic", ""))) if task.get("topic") else ""
    render_cfg = task.get("render") or {}
    page_break_before = bool(render_cfg.get("page_break_before", False))
    soft_page_break_before = render_cfg.get("soft_page_break_before", None)

    lines: list[str] = []
    if page_break_before:
        lines.append(r"\newpage")
    elif soft_page_break_before is not None:
        # Soft break: only start a new page if less than X of page height is free.
        try:
            ratio = float(soft_page_break_before)
        except Exception:
            ratio = 0.30
        ratio = max(0.05, min(0.95, ratio))
        lines.append(rf"\Needspace{{{ratio:.2f}\textheight}}")

    lines.extend([
        rf"\section*{{{name}}}",
        rf"\textbf{{Punkte:}} {points}\\",
    ])
    if topic:
        lines.append(
            rf"\textbf{{Thema:}} {topic}\\"
        )

    lines.append("")
    lines.append(statement)
    lines.append("")

    task_assets = task.get("assets") or []
    if task_assets:
        lines.append(render_assets_block(task_file, out_dir, task_assets))
        lines.append("")

    parts = task.get("parts") or []
    if parts:
        lines.append(r"\subsection*{Teilaufgaben}")
        lines.append(r"\begin{enumerate}[label=(\alph*)]")
        for part in parts:
            ptext = latex_escape(str(part.get("text", "")))
            ppoints = part.get("points", None)
            if ppoints is not None:
                lines.append(rf"\item {ptext} \hfill \textit{{({ppoints} P)}}")
            else:
                lines.append(rf"\item {ptext}")

            part_assets = part.get("assets") or []
            if part_assets:
                lines.append(render_assets_block(task_file, out_dir, part_assets))
            part_workspace = part.get("workspace") or []
            if part_workspace:
                lines.append(r"\par\smallskip\textit{Arbeitsbereich:}\par\smallskip")
                lines.append(render_workspace_blocks(part_workspace, latex_escape, in_list_item=True))
        lines.append(r"\end{enumerate}")
    else:
        # If there are no parts, show task-level workspace directly below statement/assets.
        task_workspace = task.get("workspace") or []
        if task_workspace:
            lines.append(r"\subsection*{Arbeitsbereich}")
            lines.append(render_workspace_blocks(task_workspace, latex_escape, in_list_item=False))

    # If parts exist and a task-level workspace is also present, keep it as a fallback area.
    if parts:
        task_workspace = task.get("workspace") or []
        if task_workspace:
            lines.append(r"\subsection*{Zusätzlicher Arbeitsbereich}")
            lines.append(render_workspace_blocks(task_workspace, latex_escape, in_list_item=False))

    return "\n".join(lines)


def build_tex(tasks: list[tuple[Path, dict[str, Any]]], out_dir: Path, title: str) -> str:
    body = []
    for task_file, task in tasks:
        body.append(render_task(task_file, task, out_dir))
        body.append(r"\vspace{1em}")
        body.append(r"\hrule")
        body.append(r"\vspace{1em}")

    return "\n".join(
        [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[ngerman]{babel}",
            r"\usepackage{geometry}",
            r"\usepackage{graphicx}",
            r"\usepackage{needspace}",
            r"\usepackage{enumitem}",
            r"\usepackage{parskip}",
            r"\usepackage{tikz}",
            r"\geometry{margin=2cm}",
            r"\begin{document}",
            rf"\section*{{{latex_escape(title)}}}",
            "",
            *body,
            r"\end{document}",
            "",
        ]
    )


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
    # Two passes for stable refs/layout.
    subprocess.run(cmd, check=True)
    subprocess.run(cmd, check=True)
    print(f"PDF created: {out_dir / (tex_file.stem + '.pdf')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="JSON file or directory with JSON files")
    ap.add_argument("--output-dir", default="out_pdf", help="Output directory for tex/pdf")
    ap.add_argument("--name", default="exam", help="Base name for generated tex/pdf")
    ap.add_argument("--title", default="Aufgaben", help="Document title")
    ap.add_argument("--no-compile", action="store_true", help="Only generate .tex, do not run pdflatex")
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = read_tasks(input_path)
    tex_file = out_dir / f"{args.name}.tex"
    tex_content = build_tex(tasks, out_dir, args.title)
    tex_file.write_text(tex_content, encoding="utf-8")
    print(f"LaTeX written: {tex_file}")

    if not args.no_compile:
        compile_pdf(tex_file, out_dir)


if __name__ == "__main__":
    main()

