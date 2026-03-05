#!/usr/bin/env python3
"""
workspace_latex.py

Reusable LaTeX rendering for workspace blocks.
Separated from json_to_pdf.py so it can be tested independently.
"""

from __future__ import annotations

from typing import Any, Callable


GRID_WIDTH_CM = 17.0  # With A4 and 2cm margins this matches \textwidth exactly.


def _grid_step_cfg(grid_name: str) -> tuple[float, float]:
    # (minor step cm, major step cm)
    if grid_name == "karo_1cm":
        return 1.0, 1.0
    if grid_name == "millimeter":
        return 0.1, 0.5
    return 0.5, 1.0


def _center_workspace_block(tex: str) -> str:
    # Default centering for normal (non-list) contexts.
    return (
        r"\par\noindent"
        + "\n"
        + r"\begin{minipage}{\textwidth}\centering"
        + "\n"
        + tex
        + "\n"
        + r"\end{minipage}\par"
    )


def _center_workspace_block_in_list(tex: str) -> str:
    # In list items, compensate the item indentation first.
    return (
        r"\par\noindent\hspace*{-\leftmargin}"
        + "\n"
        + r"\begin{minipage}{\textwidth}\centering"
        + "\n"
        + tex
        + "\n"
        + r"\end{minipage}\par"
    )


def render_workspace_blocks(
    workspace: list[dict[str, Any]],
    latex_escape: Callable[[str], str],
    in_list_item: bool = False,
) -> str:
    if not workspace:
        return ""

    blocks: list[str] = []
    wrap = _center_workspace_block_in_list if in_list_item else _center_workspace_block
    for w in workspace:
        wtype = str(w.get("type", "")).strip()
        if wtype == "lines":
            try:
                n = int(w.get("lines", 4))
            except Exception:
                n = 4
            n = max(1, min(n, 60))
            lines = []
            for _ in range(n):
                lines.append(r"\noindent\rule{\linewidth}{0.4pt}\\[0.45em]")
            blocks.append(wrap("\n".join(lines)))
            continue

        if wtype in ("blank", "grid"):
            try:
                h = float(w.get("height_cm", 3))
            except Exception:
                h = 3.0
            h = max(0.5, min(h, 25.0))
            if wtype == "blank":
                blocks.append(
                    rf"\vspace*{{{h:.2f}cm}}"
                )
                continue

            # grid
            grid_name = str(w.get("grid", "karo_5mm"))
            step_cm, major_step_cm = _grid_step_cfg(grid_name)

            blocks.append(wrap(
                r"\begin{tikzpicture}[x=1cm,y=1cm]" + "\n" +
                rf"\def\GridW{{{GRID_WIDTH_CM:.1f}}}" + "\n" +
                rf"\def\GridH{{{h:.2f}}}" + "\n" +
                rf"\draw[step={step_cm:.3f}cm, line width=0.12pt, color=gray!50] (0,0) grid (\GridW,\GridH);" + "\n" +
                rf"\draw[step={major_step_cm:.3f}cm, line width=0.20pt, color=gray!75] (0,0) grid (\GridW,\GridH);" + "\n" +
                r"\draw[line width=0.35pt, color=black!70] (0,0) rectangle (\GridW,\GridH);" + "\n" +
                r"\end{tikzpicture}"
            ))
            continue

        if wtype == "coord_grid":
            xmin = float(w.get("xmin", -6))
            xmax = float(w.get("xmax", 6))
            ymin = float(w.get("ymin", -2))
            ymax = float(w.get("ymax", 7))
            if xmax <= xmin:
                xmax = xmin + 1.0
            if ymax <= ymin:
                ymax = ymin + 1.0

            unit_cm = float(w.get("unit_cm", 1.0) or 1.0)
            unit_cm = max(0.1, min(unit_cm, 3.0))
            width_cm = (xmax - xmin) * unit_cm
            height_cm = (ymax - ymin) * unit_cm
            grid_name = str(w.get("grid", "karo_5mm"))
            step_cm, major_step_cm = _grid_step_cfg(grid_name)

            x0_cm = (0.0 - xmin) * unit_cm
            y0_cm = (0.0 - ymin) * unit_cm

            x_axis = ""
            y_axis = ""
            origin = ""
            axis_labels = ""
            if ymin <= 0 <= ymax:
                x_axis = rf"\draw[->, line width=0.90pt, color=black] (0,{y0_cm:.3f}) -- (\GridW,{y0_cm:.3f});" + "\n"
            if xmin <= 0 <= xmax:
                y_axis = rf"\draw[->, line width=0.90pt, color=black] ({x0_cm:.3f},0) -- ({x0_cm:.3f},\GridH);" + "\n"
            if xmin <= 0 <= xmax and ymin <= 0 <= ymax:
                origin = rf"\node[anchor=north east, font=\scriptsize] at ({x0_cm:.3f},{y0_cm:.3f}) {{0}};" + "\n"
                # Axis labels with offset so they don't overlap the axis lines.
                x_label_x = width_cm + 0.18
                x_label_y = y0_cm + 0.18
                y_label_x = x0_cm + 0.18
                y_label_y = height_cm + 0.12
                axis_labels += rf"\node[anchor=west, font=\small] at ({x_label_x:.3f},{x_label_y:.3f}) {{x}};" + "\n"
                axis_labels += rf"\node[anchor=south, font=\small] at ({y_label_x:.3f},{y_label_y:.3f}) {{y}};" + "\n"

            blocks.append(wrap(
                r"\begin{tikzpicture}[x=1cm,y=1cm]" + "\n" +
                rf"\def\GridW{{{width_cm:.3f}}}" + "\n" +
                rf"\def\GridH{{{height_cm:.3f}}}" + "\n" +
                rf"\draw[step={step_cm:.3f}cm, line width=0.12pt, color=gray!50] (0,0) grid (\GridW,\GridH);" + "\n" +
                rf"\draw[step={major_step_cm:.3f}cm, line width=0.20pt, color=gray!75] (0,0) grid (\GridW,\GridH);" + "\n" +
                r"\draw[line width=0.35pt, color=black!70] (0,0) rectangle (\GridW,\GridH);" + "\n" +
                x_axis + y_axis + origin + axis_labels +
                r"\end{tikzpicture}"
            ))
            continue

        # Unknown workspace type: keep visible note instead of dropping it silently.
        blocks.append(rf"\textit{{Unbekannter workspace-Typ: {latex_escape(wtype)}}}")

    return "\n\n".join(blocks)
