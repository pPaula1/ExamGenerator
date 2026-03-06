#!/usr/bin/env python3
"""
render_tasks.py
task.json -> intermediate Markdown (+ generated plot assets)

Highlights:
- Default image format is PNG (DOCX-friendly).
- Supports --img-format png|svg|both
- Renders assets from:
    - task["assets"]
    - each part["assets"]
- Supports generator.type == "function_plot" (2D y=f(x) plots).
- Unknown generator types become a Markdown note (no crash).

Usage:
  python render_tasks.py --tasks-dir data/tasks --out-dir out --single-md exam.md
  python render_tasks.py --tasks-dir data/tasks --out-dir out --single-md exam.md --img-format both
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt


# Allowed names in expressions (numpy-backed).
SAFE_NS = {
    "np": np,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "exp": np.exp,
    "log": np.log,   # natural log
    "sqrt": np.sqrt,
    "pi": np.pi,
    "abs": np.abs,
}


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def safe_eval_expr(expr: str, x: np.ndarray) -> np.ndarray:
    """
    Evaluate an expression like '3*cos(x)' or '-0.5*x**2+1' using numpy.
    - '^' is converted to '**'
    - builtins are disabled
    """
    expr = (expr or "").strip().replace("^", "**")
    local_ns = dict(SAFE_NS)
    local_ns["x"] = x
    return eval(expr, {"__builtins__": {}}, local_ns)


def md_escape(s: Any) -> str:
    return str(s) if s is not None else ""


def _render_function_plot_to_file(
    gen: Dict[str, Any],
    out_path: Path,
) -> Optional[str]:
    """
    Renders a function_plot generator into out_path (png/svg).
    Returns error message if something fails; otherwise None.
    """
    axes = gen.get("axes") or {}
    functions = gen.get("functions") or []

    x_range = axes.get("x_range") or [-5, 5]
    y_range = axes.get("y_range")  # optional
    grid = axes.get("grid", True)

    xmin, xmax = float(x_range[0]), float(x_range[1])
    x = np.linspace(xmin, xmax, 900)

    fig = plt.figure()
    ax = fig.add_subplot(111)

    try:
        for fn in functions:
            expr = fn.get("expr", "")
            dom = fn.get("domain") or [xmin, xmax]
            dmin, dmax = float(dom[0]), float(dom[1])

            mask = (x >= dmin) & (x <= dmax)
            y = np.full_like(x, np.nan, dtype=float)
            y[mask] = safe_eval_expr(expr, x[mask]).astype(float)
            ax.plot(x, y)  # no explicit colors

        # optional points
        for pt in gen.get("points") or []:
            ax.plot([pt["x"]], [pt["y"]], marker="o")
            if pt.get("label"):
                ax.text(pt["x"], pt["y"], f' {pt["label"]}')

        ax.set_xlim(xmin, xmax)
        if y_range and len(y_range) == 2:
            ax.set_ylim(float(y_range[0]), float(y_range[1]))
        ax.set_xlabel(axes.get("x_label", "x"))
        ax.set_ylabel(axes.get("y_label", "y"))
        if grid:
            ax.grid(True)

        fmt = out_path.suffix.lstrip(".").lower()
        if fmt == "png":
            fig.savefig(out_path, format="png", dpi=200, bbox_inches="tight")
        elif fmt == "svg":
            fig.savefig(out_path, format="svg", bbox_inches="tight")
        else:
            return f"Unsupported output format: {fmt}"

    except Exception as e:
        return str(e)
    finally:
        plt.close(fig)

    return None


def render_plot_asset(
    asset: Dict[str, Any],
    out_assets_dir: Path,
    slug: str,
    img_format: str,
) -> List[str]:
    """
    Returns markdown lines for the asset.
    If img_format == both: generate both png and svg, but reference png in markdown (DOCX-friendly).
    """
    gen = asset.get("generator") or {}
    caption = asset.get("caption") or ""

    gtype = gen.get("type")
    if gtype != "function_plot":
        note = gen.get("notes") or ""
        return [f"> **Hinweis:** Asset-Generator `{gtype}` ist im Renderer noch nicht implementiert. {note}".rstrip()]

    ensure_dir(out_assets_dir)

    md_lines: List[str] = []

    def make_and_ref(ext: str, ref_ext: str) -> Tuple[Optional[str], str]:
        out_path = out_assets_dir / f"{slug}.{ext}"
        err = _render_function_plot_to_file(gen, out_path)
        md_ref = f"assets/{slug}.{ref_ext}"
        return err, md_ref

    if img_format == "png":
        err, md_ref = make_and_ref("png", "png")
        if err:
            return [f"> **Plot-Fehler:** `{err}`"]
        return [f"![{md_escape(caption)}]({md_ref})"]

    if img_format == "svg":
        err, md_ref = make_and_ref("svg", "svg")
        if err:
            return [f"> **Plot-Fehler:** `{err}`"]
        return [f"![{md_escape(caption)}]({md_ref})"]

    if img_format == "both":
        # generate both; reference png
        err_png, md_ref_png = make_and_ref("png", "png")
        err_svg, _ = make_and_ref("svg", "png")  # md ref stays png
        if err_png:
            return [f"> **Plot-Fehler (PNG):** `{err_png}`"]
        if err_svg:
            md_lines.append(f"> **Hinweis:** SVG-Plot konnte nicht erzeugt werden: `{err_svg}`")
        md_lines.append(f"![{md_escape(caption)}]({md_ref_png})")
        return md_lines

    return [f"> **Hinweis:** Unbekanntes --img-format: `{img_format}`"]


def collect_assets(task: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Returns list of (slug_suffix, asset_dict) from task and its parts.
    """
    assets: List[Tuple[str, Dict[str, Any]]] = []

    for i, a in enumerate(task.get("assets") or []):
        assets.append((f"task_asset{i+1}", a))

    for p_idx, part in enumerate(task.get("parts") or []):
        for a_idx, a in enumerate(part.get("assets") or []):
            assets.append((f"part{p_idx+1}_asset{a_idx+1}", a))

    return assets


def render_task_to_md(task: Dict[str, Any], out_assets_dir: Path, img_format: str) -> str:
    tid = task.get("id", "task")
    title = task.get("name", tid)
    points = task.get("points", 0)

    md: List[str] = []
    md.append(f"## {md_escape(title)}")
    md.append(f"*ID:* `{tid}`  |  *Punkte:* **{points}**")
    md.append("")

    statement = task.get("statement", "")
    if statement:
        md.append(md_escape(statement))
        md.append("")

    # Assets (task + parts)
    for suffix, asset in collect_assets(task):
        gen = asset.get("generator")
        if gen:
            slug = f"{tid}_{suffix}"
            md.extend(render_plot_asset(asset, out_assets_dir, slug, img_format))
            md.append("")
        else:
            # fallback: static path
            p = asset.get("path")
            if p:
                cap = asset.get("caption") or ""
                md.append(f"![{md_escape(cap)}]({md_escape(p)})")
                md.append("")

    parts = task.get("parts") or []
    if parts:
        md.append("### Teilaufgaben")
        for part in parts:
            pid = part.get("id", "")
            ptxt = part.get("text", "")
            ppts = part.get("points")
            bullet = f"**({pid})** {md_escape(ptxt)}"
            if ppts is not None:
                bullet += f"  *(BE: {ppts})*"
            md.append(f"- {bullet}")
        md.append("")

    return "\n".join(md).strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", default="data/tasks")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--single-md", default="")
    ap.add_argument("--img-format", choices=["png", "svg", "both"], default="png",
                    help="Image format for plots. Use png for DOCX; svg for PDF; both to generate both but reference png.")
    args = ap.parse_args()

    tasks_dir = Path(args.tasks_dir)
    out_dir = Path(args.out_dir)
    out_assets = out_dir / "assets"
    ensure_dir(out_assets)
    ensure_dir(out_dir)

    task_files = sorted(tasks_dir.glob("*.json"))
    if not task_files:
        raise SystemExit(f"No task json files found in {tasks_dir.resolve()}")

    rendered: List[Tuple[str, str]] = []
    for tf in task_files:
        task = json.loads(tf.read_text(encoding="utf-8"))

        # Minimal required keys check
        for k in ("id", "name", "points", "statement"):
            if k not in task:
                raise SystemExit(f"{tf.name}: missing required field '{k}'")

        md = render_task_to_md(task, out_assets, args.img_format)
        rendered.append((task["id"], md))

    if args.single_md:
        out_md = out_dir / args.single_md
        content: List[str] = ["# Aufgaben\n"]
        for _, md in rendered:
            content.append(md)
            content.append("\n")
        out_md.write_text("\n".join(content), encoding="utf-8")
        print(f"Wrote combined markdown: {out_md}")
    else:
        for tid, md in rendered:
            out_md = out_dir / f"{tid}.md"
            out_md.write_text(md, encoding="utf-8")
        print(f"Wrote {len(rendered)} markdown files into: {out_dir.resolve()}")

    print(f"Plots format: {args.img_format} (referenced in Markdown)")
    print("Done.")


if __name__ == "__main__":
    main()
