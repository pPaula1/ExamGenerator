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
from schema_utils import validate_instance


def latex_escape(text: str) -> str:
    """Escape plain text while keeping inline LaTeX math ($...$) intact.

    Also converts underscore runs (e.g. ___) in normal text into visible
    answer lines, so authors can type blanks without raw LaTeX.
    """
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
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "$" and (i == 0 or text[i - 1] != "\\"):
            in_math = not in_math
            out.append("$")
            i += 1
            continue
        if in_math:
            out.append(ch)
            i += 1
        else:
            # Treat three or more consecutive underscores as a fill-in line.
            if ch == "_":
                j = i
                while j < n and text[j] == "_":
                    j += 1
                run_len = j - i
                if run_len >= 3:
                    width_cm = max(0.8, min(8.0, run_len * 0.30))
                    out.append(rf"\underline{{\hspace{{{width_cm:.2f}cm}}}}")
                else:
                    out.extend(replacements.get("_", "_") for _ in range(run_len))
                i = j
                continue
            out.append(replacements.get(ch, ch))
            i += 1
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
        validate_instance(data, "task", label=str(f))
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
    show_caption = asset.get("show_caption", False)
    if isinstance(show_caption, str):
        show_caption = show_caption.strip().lower() in {"1", "true", "yes", "on"}

    lines = [rf"\includegraphics[width={width}]{{{rel_tex}}}"]
    if show_caption and caption:
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


def _matching_item_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("text", "")).strip()
    return ""


def render_matching_block(matching: dict[str, Any]) -> str:
    left_items = [_matching_item_text(item) for item in (matching.get("left_items") or [])]
    right_items = [_matching_item_text(item) for item in (matching.get("right_items") or [])]

    left_items = [latex_escape(t) for t in left_items if t]
    right_items = [latex_escape(t) for t in right_items if t]
    if not left_items or not right_items:
        return ""

    max_rows = max(len(left_items), len(right_items))
    row_step_cm = 1.0
    top_y = (max_rows - 1) * row_step_cm

    left_text_width_cm = 5.8
    right_text_width_cm = 5.8
    center_gap_cm = 3.6
    dot_radius_pt = 2.2
    dot_line_width_pt = 0.6

    left_text_x = 0.0
    left_dot_x = left_text_x + left_text_width_cm + 0.25
    right_dot_x = left_dot_x + center_gap_cm
    right_text_x = right_dot_x + 0.25

    def right_y(idx: int) -> float:
        if len(right_items) == 1:
            return top_y / 2.0
        return top_y - (top_y * idx / (len(right_items) - 1))

    lines = [
        r"\begin{center}",
        r"\begin{tikzpicture}[x=1cm,y=1cm]",
    ]

    for idx, text in enumerate(left_items):
        y = top_y - idx * row_step_cm
        lines.append(
            rf"\node[anchor=east,align=right,text width={left_text_width_cm:.2f}cm] at ({(left_dot_x - 0.25):.2f},{y:.2f}) {{{text}}};"
        )
        lines.append(
            rf"\filldraw[draw=black,fill=white,line width={dot_line_width_pt:.2f}pt] ({left_dot_x:.2f},{y:.2f}) circle ({dot_radius_pt:.2f}pt);"
        )

    for idx, text in enumerate(right_items):
        y = right_y(idx)
        lines.append(
            rf"\filldraw[draw=black,fill=white,line width={dot_line_width_pt:.2f}pt] ({right_dot_x:.2f},{y:.2f}) circle ({dot_radius_pt:.2f}pt);"
        )
        lines.append(
            rf"\node[anchor=west,align=left,text width={right_text_width_cm:.2f}cm] at ({right_text_x:.2f},{y:.2f}) {{{text}}};"
        )

    lines.extend([
        r"\end{tikzpicture}",
        r"\end{center}",
    ])
    return "\n".join(lines)


def _format_formula_latex(formula_raw: str, align: str) -> str:
    f = formula_raw.strip()
    if not f:
        return ""
    has_math_delims = ("$" in f) or (r"\(" in f) or (r"\[" in f) or (r"\begin{" in f)
    if align == "center":
        return f if has_math_delims else rf"\[{f}\]"
    return f if has_math_delims else rf"\(\displaystyle {f}\)"


def render_textboxes_block(textboxes: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    align_macro = {
        "left": r"\raggedright",
        "center": r"\centering",
        "right": r"\raggedleft",
    }
    align_env = {
        "left": "flushleft",
        "center": "center",
        "right": "flushright",
    }

    for box in textboxes:
        if not isinstance(box, dict):
            continue
        btype = str(box.get("type", "")).strip().lower()
        align = str(box.get("align", "left")).strip().lower()
        if align not in align_macro:
            align = "left"
        boxed = box.get("boxed", False)
        if isinstance(boxed, str):
            boxed = boxed.strip().lower() in {"1", "true", "yes", "on"}
        else:
            boxed = bool(boxed)

        content = ""
        if btype == "text":
            text = latex_escape(str(box.get("text", "")).strip())
            if not text:
                continue
            content = text
        elif btype == "formula":
            formula = _format_formula_latex(str(box.get("formula", "")), align)
            if not formula:
                continue
            content = formula
        else:
            continue

        if boxed:
            blocks.append(
                r"\begin{center}" + "\n" +
                r"\fbox{\begin{minipage}{0.95\linewidth}" + "\n" +
                align_macro[align] + "\n" +
                content + "\n" +
                r"\end{minipage}}" + "\n" +
                r"\end{center}"
            )
        else:
            env = align_env[align]
            blocks.append(
                rf"\begin{{{env}}}" + "\n" +
                content + "\n" +
                rf"\end{{{env}}}"
            )

    return "\n\n".join(blocks)


def _table_cell_text(cell: Any) -> str:
    return latex_escape(" ".join(str(cell).split()))


def _normalize_table_rows(rows: list[Any], col_count: int) -> list[list[str]]:
    normalized: list[list[str]] = []
    for row in rows:
        if isinstance(row, list):
            values = row
        else:
            values = [row]
        text_row = [_table_cell_text(v) for v in values[:col_count]]
        if len(text_row) < col_count:
            text_row.extend([""] * (col_count - len(text_row)))
        normalized.append(text_row)
    return normalized


def _normalize_table_alignments(raw_align: Any, col_count: int) -> list[str]:
    allowed = {"left", "center", "right"}
    if isinstance(raw_align, str):
        value = raw_align.strip().lower()
        if value not in allowed:
            value = "left"
        return [value] * col_count

    if isinstance(raw_align, list) and raw_align:
        values: list[str] = []
        for entry in raw_align:
            value = str(entry).strip().lower()
            values.append(value if value in allowed else "left")
        if len(values) == 1:
            return values * col_count
        if len(values) < col_count:
            values.extend([values[-1]] * (col_count - len(values)))
        return values[:col_count]

    return ["left"] * col_count


def render_table_block(table: dict[str, Any]) -> str:
    headers_raw = table.get("headers") or []
    rows_raw = table.get("rows") or []
    if not isinstance(headers_raw, list) or not isinstance(rows_raw, list):
        return ""

    col_count = len(headers_raw)
    for row in rows_raw:
        if isinstance(row, list):
            col_count = max(col_count, len(row))
        else:
            col_count = max(col_count, 1)
    if col_count <= 0:
        return ""

    headers = [_table_cell_text(v) for v in list(headers_raw)[:col_count]]
    if len(headers) < col_count:
        headers.extend([""] * (col_count - len(headers)))
    rows = _normalize_table_rows(rows_raw, col_count)

    show_header = table.get("show_header", True)
    if isinstance(show_header, str):
        show_header = show_header.strip().lower() in {"1", "true", "yes", "on"}
    else:
        show_header = bool(show_header)

    alignments = _normalize_table_alignments(table.get("align", "left"), col_count)
    width_cfg = table.get("column_widths_cm")
    width_exprs: list[str] = []
    if (
        isinstance(width_cfg, list)
        and len(width_cfg) == col_count
        and all(isinstance(w, (int, float)) and float(w) > 0 for w in width_cfg)
    ):
        width_exprs = [f"{float(w):.2f}cm" for w in width_cfg]
    else:
        auto_width = 0.96 / col_count
        width_exprs = [f"{auto_width:.4f}\\linewidth"] * col_count

    align_map = {
        "left": r">{\raggedright\arraybackslash}",
        "center": r">{\centering\arraybackslash}",
        "right": r">{\raggedleft\arraybackslash}",
    }
    col_specs = [
        f"{align_map.get(alignments[i], align_map['left'])}p{{{width_exprs[i]}}}"
        for i in range(col_count)
    ]

    border = str(table.get("border", "full_grid")).strip().lower()
    if border not in {"full_grid", "outer", "rows", "none"}:
        border = "full_grid"
    if border in {"full_grid", "outer"}:
        colspec = "|" + "|".join(col_specs) + "|"
    else:
        colspec = "".join(col_specs)

    def _row_line(values: list[str]) -> str:
        return " & ".join(values) + r" \\"

    lines = [
        r"\begin{center}",
        r"\setlength{\tabcolsep}{6pt}",
        r"\renewcommand{\arraystretch}{1.25}",
        rf"\begin{{tabular}}{{{colspec}}}",
    ]

    if border in {"full_grid", "rows", "outer"}:
        lines.append(r"\hline")

    if show_header and headers:
        lines.append(_row_line(headers))
        if border in {"full_grid", "rows", "outer"}:
            lines.append(r"\hline")

    for row in rows:
        lines.append(_row_line(row))
        if border in {"full_grid", "rows"}:
            lines.append(r"\hline")

    if border == "outer":
        lines.append(r"\hline")

    lines.extend([
        r"\end{tabular}",
        r"\end{center}",
    ])
    return "\n".join(lines)


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
        multiple_parts = len(parts) > 1
        if multiple_parts:
            lines.append(r"\subsection*{Teilaufgaben}")
            lines.append(r"\begin{enumerate}[label=(\alph*)]")

        for part in parts:
            part_type = str(part.get("type", "text")).strip()
            ptext_raw = str(part.get("text", "")).strip()
            ptext = latex_escape(ptext_raw) if ptext_raw else ""
            ppoints = part.get("points", None)
            checkbox_items = part.get("checkbox_items") or []
            matching_data = part.get("matching") or {}
            table_data = part.get("table") or {}
            textboxes = part.get("textboxes") or []

            if multiple_parts:
                if ppoints is not None:
                    if ptext:
                        lines.append(rf"\item {ptext} \hfill \textit{{\mbox{{({ppoints}~P)}}}}")
                    else:
                        lines.append(rf"\item \hfill \textit{{\mbox{{({ppoints}~P)}}}}")
                else:
                    if ptext:
                        lines.append(rf"\item {ptext}")
                    else:
                        lines.append(r"\item")
            else:
                if ppoints is not None:
                    if ptext:
                        lines.append(rf"{ptext} \hfill \textit{{\mbox{{({ppoints}~P)}}}}")
                    else:
                        lines.append(rf"\hfill \textit{{\mbox{{({ppoints}~P)}}}}")
                elif ptext:
                    lines.append(ptext)

            if textboxes:
                textboxes_block = render_textboxes_block(textboxes)
                if textboxes_block:
                    lines.append(textboxes_block)

            if checkbox_items:
                lines.append(r"\begin{itemize}[leftmargin=1.5em,label={}]")
                for cb in checkbox_items:
                    cb_text = latex_escape(str((cb or {}).get("text", "")).strip())
                    if not cb_text:
                        continue
                    lines.append(rf"\item \fbox{{\rule{{0pt}}{{0.9em}}\hspace{{0.9em}}}} {cb_text}")
                lines.append(r"\end{itemize}")

            if part_type == "matching":
                matching_block = render_matching_block(matching_data)
                if matching_block:
                    lines.append(matching_block)
            elif part_type == "table" or (part_type == "text" and isinstance(table_data, dict) and table_data):
                table_block = render_table_block(table_data)
                if table_block:
                    lines.append(table_block)

            part_assets = part.get("assets") or []
            if part_assets:
                # Force assets to start below the item text (not inline with it).
                lines.append(r"\par\smallskip")
                lines.append(render_assets_block(task_file, out_dir, part_assets))
                lines.append(r"\par\smallskip")
            part_workspace = part.get("workspace") or []
            if part_workspace:
                lines.append(r"\par\smallskip\textit{Arbeitsbereich:}\par\smallskip")
                lines.append(
                    render_workspace_blocks(part_workspace, latex_escape, in_list_item=multiple_parts)
                )

        if multiple_parts:
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
        body.append(r"\vspace{1.0em}")
        body.append(r"\noindent\textcolor{gray!60}{\rule{\linewidth}{1.0pt}}")
        body.append(r"\vspace{1.0em}")

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
            r"\usepackage{array}",
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

