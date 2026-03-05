#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render simple 2D GeoGebra content (.ggb) to an SVG plot.

Supported object types:
- function (single-variable y=f(x))
- point
- line (a*x + b*y + c = 0)
- segment (from point A to point B)
- vector (start point + direction)
"""

import argparse
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

CM_PER_UNIT = 1.0
PT_PER_CM = 72.0 / 2.54

# Optional but recommended:
# pip install sympy
try:
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        parse_expr,
        standard_transformations,
        implicit_multiplication_application,
        convert_xor,
    )
except ImportError as e:
    raise SystemExit(
        "Dieses Script braucht sympy. Installiere es mit:\n\n"
        "  pip install sympy\n"
    ) from e


@dataclass
class GGFunction:
    label: str
    expr_raw: str


@dataclass
class GGPoint:
    label: str
    x: float
    y: float


@dataclass
class GGLine:
    label: str
    a: float
    b: float
    c: float


@dataclass
class GGSegment:
    label: str
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class GGVector:
    label: str
    x0: float
    y0: float
    dx: float
    dy: float


def read_geogebra_xml(ggb_path: str) -> bytes:
    with zipfile.ZipFile(ggb_path, "r") as zf:
        # Standard name inside .ggb
        try:
            return zf.read("geogebra.xml")
        except KeyError:
            # Some files may contain geogebra_javascript.js etc, but usually geogebra.xml exists.
            raise SystemExit("Konnte 'geogebra.xml' in der .ggb Datei nicht finden.")


def _safe_float(s: str) -> Optional[float]:
    # GeoGebra may store numbers as strings, sometimes with commas in older locales.
    s = s.strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_objects(
    xml_bytes: bytes,
) -> Tuple[List[GGFunction], List[GGPoint], List[GGLine], List[GGSegment], List[GGVector]]:
    """Extract supported objects from geogebra.xml bytes."""
    root = ET.fromstring(xml_bytes)

    functions: List[GGFunction] = []
    points: List[GGPoint] = []
    lines: List[GGLine] = []
    segments: List[GGSegment] = []
    vectors: List[GGVector] = []
    points_by_label = {}
    segment_labels = set()

    # GeoGebra XML typically has <construction> ... <element type="function" label="f"> ...
    for el in root.iter("element"):
        el_type = el.attrib.get("type", "").lower()
        label = el.attrib.get("label", "")

        if el_type == "function":
            # Try to find expression
            expr_node = el.find("expression")
            if expr_node is not None and "exp" in expr_node.attrib:
                functions.append(GGFunction(label=label or "f", expr_raw=expr_node.attrib["exp"]))
            else:
                # Sometimes expression is elsewhere; also allow any nested <expression exp="...">
                for expr in el.iter("expression"):
                    exp = expr.attrib.get("exp")
                    if exp:
                        functions.append(GGFunction(label=label or "f", expr_raw=exp))
                        break

        elif el_type == "point":
            # Coordinate storage often under <coords x="..." y="..." z="1"/>
            coords = el.find("coords")
            if coords is not None:
                x = _safe_float(coords.attrib.get("x", ""))
                y = _safe_float(coords.attrib.get("y", ""))
                z = _safe_float(coords.attrib.get("z", "1"))
                # Convert homogeneous coords if needed: (x/z, y/z)
                if x is not None and y is not None and (z is None or z == 0):
                    # can't use z=0
                    pass
                elif x is not None and y is not None and z is not None and z != 0:
                    p = GGPoint(label=label or "P", x=x / z, y=y / z)
                    points.append(p)
                    if label:
                        points_by_label[label] = p

        elif el_type == "line":
            # GeoGebra line coefficients are commonly stored as: a*x + b*y + c = 0
            coords = el.find("coords")
            if coords is not None:
                a = _safe_float(coords.attrib.get("x", ""))
                b = _safe_float(coords.attrib.get("y", ""))
                c = _safe_float(coords.attrib.get("z", ""))
                if a is not None and b is not None and c is not None and not (
                    math.isclose(a, 0.0, abs_tol=1e-12) and math.isclose(b, 0.0, abs_tol=1e-12)
                ):
                    lines.append(GGLine(label=label or "g", a=a, b=b, c=c))
        elif el_type == "segment":
            if label:
                segment_labels.add(label)
        elif el_type == "vector":
            coords = el.find("coords")
            if coords is None:
                continue
            x = _safe_float(coords.attrib.get("x", ""))
            y = _safe_float(coords.attrib.get("y", ""))
            z = _safe_float(coords.attrib.get("z", "0"))
            if x is None or y is None:
                continue
            # Vector coordinates are typically stored with z=0.
            dx, dy = (x, y) if (z is None or math.isclose(z, 0.0, abs_tol=1e-12)) else (x / z, y / z)
            sp_node = el.find("startPoint")
            start_label = sp_node.attrib.get("exp", "") if sp_node is not None else ""
            p0 = points_by_label.get(start_label)
            x0, y0 = (p0.x, p0.y) if p0 is not None else (0.0, 0.0)
            vectors.append(GGVector(label=label or "v", x0=x0, y0=y0, dx=dx, dy=dy))

    # Fallback: sometimes functions appear as <expression label="f" exp="..."/> at top-level
    if not functions:
        for expr in root.iter("expression"):
            lbl = expr.attrib.get("label")
            exp = expr.attrib.get("exp")
            if lbl and exp:
                # heuristic: treat as function if "x" appears
                if re.search(r"\bx\b", exp):
                    functions.append(GGFunction(label=lbl, expr_raw=exp))

    # Segment endpoints are linked through commands:
    # <command name="Segment"><input a0="A" a1="B"/><output a0="f"/></command>
    for cmd in root.iter("command"):
        if cmd.attrib.get("name", "").lower() != "segment":
            continue
        inp = cmd.find("input")
        out = cmd.find("output")
        if inp is None or out is None:
            continue
        p1 = points_by_label.get(inp.attrib.get("a0", ""))
        p2 = points_by_label.get(inp.attrib.get("a1", ""))
        out_label = out.attrib.get("a0", "")
        if p1 is None or p2 is None:
            continue
        if segment_labels and out_label and out_label not in segment_labels:
            continue
        segments.append(GGSegment(label=out_label or "s", x1=p1.x, y1=p1.y, x2=p2.x, y2=p2.y))

    return functions, points, lines, segments, vectors


def geogebra_to_sympy(expr: str) -> sp.Expr:
    """
    Convert common GeoGebra syntax to something sympy can parse.
    Handles: ^, pi symbol, common functions.
    """
    s = expr.strip()
    if "=" in s:
        s = s.split("=", 1)[1].strip()

    # Common replacements
    s = s.replace("π", "pi")
    s = s.replace("·", "*")
    s = s.replace("^", "**")  # in case convert_xor doesn't catch due to pre-processing

    # GeoGebra sometimes uses e^x or exp(x) etc; sympy understands exp()
    # ln(x) -> log(x)
    s = re.sub(r"\bln\s*\(", "log(", s)

    # GeoGebra: abs(x) might be abs(x) or |x| (rare in exp attribute). Handle abs().
    # Handle power like x² (rare in xml exp, but just in case)
    s = s.replace("²", "**2").replace("³", "**3")

    x = sp.Symbol("x")
    local_dict = {
        "x": x,
        "pi": sp.pi,
        "e": sp.E,
        "sin": sp.sin,
        "cos": sp.cos,
        "tan": sp.tan,
        "asin": sp.asin,
        "acos": sp.acos,
        "atan": sp.atan,
        "sqrt": sp.sqrt,
        "log": sp.log,
        "ln": sp.log,
        "abs": sp.Abs,
        "floor": sp.floor,
        "ceil": sp.ceiling,
        "exp": sp.exp,
    }

    transformations = standard_transformations + (
        implicit_multiplication_application,
        convert_xor,
    )

    try:
        return parse_expr(s, local_dict=local_dict, transformations=transformations, evaluate=True)
    except Exception as e:
        raise ValueError(f"Konnte Ausdruck nicht parsen: {expr!r} (nach Konvertierung: {s!r})") from e


def _integer_ticks(min_v: float, max_v: float, *, drop_upper: bool) -> List[int]:
    """Return integer ticks in [ceil(min_v), floor(max_v)], optionally without max_v."""
    ticks = list(range(math.ceil(min_v), math.floor(max_v) + 1))
    if drop_upper:
        ticks = [t for t in ticks if not math.isclose(t, max_v, abs_tol=1e-9)]
    return ticks


def setup_axes_with_arrows(ax, xmin, xmax, ymin, ymax):
    """Style axes, add 1-unit grid, arrows and axis labels."""
    # Clean look: hide top/right spines, place axes at origin
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Move left/bottom spines to zero (axes through origin)
    ax.spines["left"].set_position(("data", 0))
    ax.spines["bottom"].set_position(("data", 0))

    # Hide spines themselves; we will draw arrows
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)

    # Ticks
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.tick_params(direction="out", length=4)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks(_integer_ticks(xmin, xmax, drop_upper=True))
    ax.set_yticks(_integer_ticks(ymin, ymax, drop_upper=True))
    ax.grid(True, which="major", color="#d0d0d0", linewidth=0.8)
    # Avoid overlapping numbers at arrow tips and hide origin tick labels.
    ax.xaxis.set_major_formatter(
        FuncFormatter(
            lambda v, _: ""
            if (math.isclose(v, xmax, abs_tol=1e-9) or math.isclose(v, 0.0, abs_tol=1e-9))
            else f"{v:g}"
        )
    )
    ax.yaxis.set_major_formatter(
        FuncFormatter(
            lambda v, _: ""
            if (math.isclose(v, ymax, abs_tol=1e-9) or math.isclose(v, 0.0, abs_tol=1e-9))
            else f"{v:g}"
        )
    )

    # Single origin label, positioned a bit left-below the (0,0) point.
    if xmin <= 0 <= xmax and ymin <= 0 <= ymax:
        ax.annotate(
            "0",
            xy=(0, 0),
            xytext=(-8, -8),
            textcoords="offset points",
            ha="right",
            va="top",
            fontsize=10,
        )

    # Draw axis arrows (both directions only positive arrowheads requested; typically end at max)
    # x-axis
    ax.annotate(
        "",
        xy=(xmax, 0),
        xytext=(xmin, 0),
        arrowprops=dict(
            arrowstyle="->",
            linewidth=1.5,
            edgecolor="black",
            facecolor="black",
            shrinkA=0,
            shrinkB=0,
            mutation_scale=14,
        ),
        clip_on=False,
    )
    # y-axis
    ax.annotate(
        "",
        xy=(0, ymax),
        xytext=(0, ymin),
        arrowprops=dict(
            arrowstyle="->",
            linewidth=1.5,
            edgecolor="black",
            facecolor="black",
            shrinkA=0,
            shrinkB=0,
            mutation_scale=14,
        ),
        clip_on=False,
    )

    # Axis labels anchored to arrow tips in data coordinates.
    # This keeps label placement stable for different plot ranges/sizes.
    ax.annotate(
        "x",
        xy=(xmax, 0),
        xytext=(-8, -12),
        textcoords="offset points",
        ha="right",
        va="top",
        fontsize=12,
        fontweight="bold",
    )
    ax.annotate(
        "y",
        xy=(0, ymax),
        xytext=(-10, -4),
        textcoords="offset points",
        ha="right",
        va="top",
        fontsize=12,
        fontweight="bold",
    )


def _distance_point_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance from point P to the segment AB."""
    vx, vy = x2 - x1, y2 - y1
    wx, wy = px - x1, py - y1
    seg_len_sq = vx * vx + vy * vy
    if seg_len_sq <= 1e-18:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg_len_sq))
    cx, cy = x1 + t * vx, y1 + t * vy
    return math.hypot(px - cx, py - cy)


def _choose_point_label_offset(
    p: GGPoint,
    *,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    lines: List[GGLine],
    segments: List[GGSegment],
    vectors: List[GGVector],
    funcs: List[Callable[[float], float]],
) -> Tuple[int, int]:
    """Pick a simple label offset that avoids axes and plotted objects."""
    candidates = [(6, 6), (6, -10), (-10, 6), (-10, -10), (12, 0), (-14, 0), (0, 12), (0, -12)]
    units_per_point = 1.0 / (PT_PER_CM * CM_PER_UNIT)
    margin = 0.12
    best = candidates[0]
    best_score = float("inf")

    for dx_pt, dy_pt in candidates:
        lx = p.x + dx_pt * units_per_point
        ly = p.y + dy_pt * units_per_point
        score = 0.0

        # Keep label anchor inside plotting window.
        if lx < xmin + margin or lx > xmax - margin or ly < ymin + margin or ly > ymax - margin:
            score += 50.0

        # Avoid axes.
        if abs(lx) < margin:
            score += 25.0
        if abs(ly) < margin:
            score += 25.0

        # Avoid infinite lines.
        for ln in lines:
            d = abs(ln.a * lx + ln.b * ly + ln.c) / math.hypot(ln.a, ln.b)
            if d < margin:
                score += 30.0 * (margin - d + 1.0)

        # Avoid segments.
        for sg in segments:
            d = _distance_point_to_segment(lx, ly, sg.x1, sg.y1, sg.x2, sg.y2)
            if d < margin:
                score += 30.0 * (margin - d + 1.0)

        # Avoid vectors (as segment from start to tip).
        for v in vectors:
            d = _distance_point_to_segment(lx, ly, v.x0, v.y0, v.x0 + v.dx, v.y0 + v.dy)
            if d < margin:
                score += 30.0 * (margin - d + 1.0)

        # Avoid function curves by checking y(x) at label x.
        for f in funcs:
            try:
                fy = float(f(lx))
                if math.isfinite(fy):
                    d = abs(fy - ly)
                    if d < margin:
                        score += 30.0 * (margin - d + 1.0)
            except Exception:
                pass

        if score < best_score:
            best_score = score
            best = (dx_pt, dy_pt)

    return best


def plot_ggb(
    ggb_path: str,
    out_svg: str,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    samples: int = 2000,
    plot_points: bool = True,
):
    """Render parsed GeoGebra objects to an SVG with fixed physical scale."""
    xml_bytes = read_geogebra_xml(ggb_path)
    functions, points, lines, segments, vectors = extract_objects(xml_bytes)

    if not functions and not points and not lines and not segments and not vectors:
        raise SystemExit(
            "In der Datei wurden keine (unterstützten) Funktionen, Punkte, Linien, Segmente oder Vektoren gefunden."
        )

    if samples < 2:
        raise SystemExit("Ungültiger Wert für --samples: mindestens 2.")

    x = sp.Symbol("x")
    xs = [xmin + (xmax - xmin) * i / (samples - 1) for i in range(samples)]

    # Physical scaling requirement: 1 coordinate unit = 1 cm in the plot area.
    x_units = xmax - xmin
    y_units = ymax - ymin
    if x_units <= 0 or y_units <= 0:
        raise SystemExit("Ungültiger Bereich: xmax muss > xmin und ymax muss > ymin sein.")

    cm_per_unit = 1.0
    inch_per_cm = 1.0 / 2.54
    ax_width_in = x_units * cm_per_unit * inch_per_cm
    ax_height_in = y_units * cm_per_unit * inch_per_cm

    # Fixed margins around the axis area (inches) for labels/arrows.
    left_in = 0.75
    right_in = 0.20
    bottom_in = 0.70
    top_in = 0.25

    fig_w = left_in + ax_width_in + right_in
    fig_h = bottom_in + ax_height_in + top_in
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=120)
    ax = fig.add_axes(
        [
            left_in / fig_w,
            bottom_in / fig_h,
            ax_width_in / fig_w,
            ax_height_in / fig_h,
        ]
    )
    setup_axes_with_arrows(ax, xmin, xmax, ymin, ymax)

    # Plot lines: a*x + b*y + c = 0
    for ln in lines:
        if math.isclose(ln.b, 0.0, abs_tol=1e-12):
            # Vertical line: x = -c/a
            if math.isclose(ln.a, 0.0, abs_tol=1e-12):
                continue
            xv = -ln.c / ln.a
            ax.plot([xv, xv], [ymin, ymax], linewidth=2, color="black")
            continue

        # Non-vertical line via y = (-a*x - c)/b for visible x-range
        y1 = (-ln.a * xmin - ln.c) / ln.b
        y2 = (-ln.a * xmax - ln.c) / ln.b
        ax.plot([xmin, xmax], [y1, y2], linewidth=2, color="black")

    # Plot segments
    for sg in segments:
        ax.plot([sg.x1, sg.x2], [sg.y1, sg.y2], linewidth=2, color="black")

    # Plot vectors
    for v in vectors:
        ax.annotate(
            "",
            xy=(v.x0 + v.dx, v.y0 + v.dy),
            xytext=(v.x0, v.y0),
            arrowprops=dict(
                arrowstyle="->",
                linewidth=2,
                edgecolor="black",
                facecolor="black",
                shrinkA=0,
                shrinkB=0,
                mutation_scale=12,
            ),
            clip_on=False,
        )

    # Plot functions
    function_callables: List[Callable[[float], float]] = []
    for f in functions:
        try:
            sym = geogebra_to_sympy(f.expr_raw)
            func = sp.lambdify(x, sym, modules=["math"])
            function_callables.append(func)
        except Exception as e:
            print(f"[WARN] Überspringe Funktion {f.label}: {e}")
            continue

        ys = []
        for xv in xs:
            try:
                yv = func(xv)
                # Filter out non-real / huge
                if isinstance(yv, complex):
                    ys.append(float("nan"))
                else:
                    yv = float(yv)
                    if not math.isfinite(yv) or abs(yv) > 1e6:
                        ys.append(float("nan"))
                    else:
                        ys.append(yv)
            except Exception:
                ys.append(float("nan"))

        ax.plot(xs, ys, linewidth=2)

    # Plot points (optional)
    if plot_points and points:
        px = [p.x for p in points]
        py = [p.y for p in points]
        ax.scatter(px, py, s=25)
        # Place point labels with simple collision avoidance.
        for p in points:
            dx, dy = _choose_point_label_offset(
                p,
                xmin=xmin,
                xmax=xmax,
                ymin=ymin,
                ymax=ymax,
                lines=lines,
                segments=segments,
                vectors=vectors,
                funcs=function_callables,
            )
            ax.annotate(p.label, (p.x, p.y), textcoords="offset points", xytext=(dx, dy), fontsize=9)

    # Export
    fig.savefig(out_svg, format="svg")
    plt.close(fig)

    print(f"OK: geschrieben -> {out_svg}")
    if vectors:
        print(f"Gefundene Vektoren: {len(vectors)}")
    if segments:
        print(f"Gefundene Segmente: {len(segments)}")
    if lines:
        print("Gefundene Linien:")
        for ln in lines:
            print(f"  - {ln.label}: {ln.a}*x + {ln.b}*y + {ln.c} = 0")
    if functions:
        print("Gefundene Funktionen:")
        for f in functions:
            print(f"  - {f.label}: {f.expr_raw}")
    if points and plot_points:
        print(f"Gefundene Punkte: {len(points)}")


def main():
    ap = argparse.ArgumentParser(
        description="Plot GeoGebra .ggb Datei nach festen Vorgaben als SVG (Bereich, Achsenpfeile, x/y Labels)."
    )
    ap.add_argument("ggb", help="Pfad zur .ggb Datei")
    ap.add_argument("-o", "--out", default="plot.svg", help="Ausgabe-SVG (default: plot.svg)")
    ap.add_argument("--xmin", type=float, default=-3.0)
    ap.add_argument("--xmax", type=float, default=3.0)
    ap.add_argument("--ymin", type=float, default=-3.0)
    ap.add_argument("--ymax", type=float, default=3.0)
    ap.add_argument("--samples", type=int, default=2000, help="Abtastpunkte pro Funktion (default: 2000)")
    ap.add_argument("--no-points", action="store_true", help="Punkte nicht plotten")
    args = ap.parse_args()

    plot_ggb(
        ggb_path=args.ggb,
        out_svg=args.out,
        xmin=args.xmin,
        xmax=args.xmax,
        ymin=args.ymin,
        ymax=args.ymax,
        samples=args.samples,
        plot_points=(not args.no_points),
    )


if __name__ == "__main__":
    main()
