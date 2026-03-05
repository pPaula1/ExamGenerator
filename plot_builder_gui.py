#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plot Builder GUI v5 (Expert options + per-function styling + help + pi scaling)

Core goals kept:
- WYSIWYG preview (Matplotlib) using the same 5mm worksheet grid logic as export
- Export SVG (and JSON) in one click
- Exact physical 5mm grid when printed (use 100% / actual size)

New:
- Expert dialog:
  - DPI (default 300)
  - Global function color + linewidth
  - Grid/Axes colors
  - Optional "π scaling": set cm_per_unit so that π spans N small squares (e.g. 8 squares = π)
  - Optional x-axis labels as multiples of π
- Function dialog:
  - Optional per-function color + linewidth (falls back to global defaults)
- Help button: shows common SymPy-like input examples

Install:
  py -m pip install PySide6 sympy numpy matplotlib
Run:
  py plot_builder_gui_v5_expert.py
"""

from __future__ import annotations

import json
import math
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import sympy as sp
from sympy.parsing.sympy_parser import (
    parse_expr,
    standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QSplitter,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QLabel,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter


# --------------------- SymPy parsing ---------------------

_X = sp.Symbol("x", real=True)

_ALLOWED_FUNCS = {
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "exp": sp.exp,
    "log": sp.log,
    "sqrt": sp.sqrt,
    "abs": sp.Abs,
    "pi": sp.pi,
    "E": sp.E,
}

_TRANSFORMS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

def parse_sympy(expr: str) -> sp.Expr:
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("Leerer Ausdruck.")
    local_dict = {"x": _X, **_ALLOWED_FUNCS}
    return parse_expr(expr, local_dict=local_dict, transformations=_TRANSFORMS, evaluate=True)

def safe_sample(expr: sp.Expr, x_vals: np.ndarray) -> np.ndarray:
    f = sp.lambdify(_X, expr, "numpy")
    with np.errstate(all="ignore"):
        y = f(x_vals)
    y = np.array(y, dtype=float)
    y[~np.isfinite(y)] = np.nan
    return y


# --------------------- Data model ---------------------

@dataclass
class FunctionSpec:
    id: str
    expr: str
    label: str = ""
    samples: int = 1000
    color: str = ""      # optional; empty -> global default
    linewidth: float = 0 # optional; 0 -> global default

@dataclass
class CombineSpec:
    id: str
    op: str
    args: Tuple[str, str]
    label: str = ""

@dataclass
class StyleSpec:
    background_color: str = "#ffffff"
    grid_minor_color: str = "#e8e8e8"
    grid_major_color: str = "#cfcfcf"
    axis_color: str = "#666666"
    function_color: str = "#000000"
    function_linewidth: float = 1.8

@dataclass
class ExpertSpec:
    dpi: int = 300
    show_pi_labels: bool = False
    squares_per_pi: int = 8  # if enabled, set cm_per_unit so that pi = N squares

@dataclass
class PlotSpec:
    type: str = "function_plot"
    title: str = ""
    engine: str = "matplotlib"
    format: str = "svg"

    # fixed ranges
    x_range: Tuple[float, float] = (-10.0, 10.0)
    y_range: Tuple[float, float] = (-8.0, 8.0)
    show_axes: bool = True

    # worksheet params
    paper_format: str = "A4"
    orientation: str = "portrait"
    margin_cm: float = 1.5
    grid_mm: float = 5.0
    cm_per_unit: float = 0.5
    major_every: int = 5

    style: StyleSpec = field(default_factory=StyleSpec)
    expert: ExpertSpec = field(default_factory=ExpertSpec)

    functions: List[FunctionSpec] = field(default_factory=list)
    combines: List[CombineSpec] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        d = {
            "type": self.type,
            "title": self.title,
            "engine": self.engine,
            "format": self.format,
            "axes": {
                "x_range": [self.x_range[0], self.x_range[1]],
                "y_range": [self.y_range[0], self.y_range[1]],
                "show_axes": self.show_axes,
                "aspect": "equal",
                "pi_labels": bool(self.expert.show_pi_labels),
            },
            "paper": {
                "paper_format": self.paper_format,
                "orientation": self.orientation,
                "margin_cm": self.margin_cm,
                "dpi": self.expert.dpi,
                "grid_mm": self.grid_mm,
                "cm_per_unit": self.cm_per_unit,
                "major_every": self.major_every,
                "style": {
                    "background_color": self.style.background_color,
                    "grid_minor_color": self.style.grid_minor_color,
                    "grid_major_color": self.style.grid_major_color,
                    "axis_color": self.style.axis_color,
                },
            },
            "render": {
                "function_color": self.style.function_color,
                "function_linewidth": self.style.function_linewidth,
            },
            "functions": [],
        }

        for f in self.functions:
            fd = {
                "id": f.id,
                "expr": f.expr,
                "samples": int(f.samples),
            }
            if f.label:
                fd["label"] = f.label
            # optional per-function style
            if f.color or f.linewidth:
                fd["style"] = {}
                if f.color:
                    fd["style"]["color"] = f.color
                if f.linewidth:
                    fd["style"]["linewidth"] = float(f.linewidth)
            d["functions"].append(fd)

        if self.combines:
            d["combines"] = []
            for c in self.combines:
                cd = {"id": c.id, "op": c.op, "args": [c.args[0], c.args[1]]}
                if c.label:
                    cd["label"] = c.label
                d["combines"].append(cd)

        return d


# --------------------- Combine evaluation ---------------------

def build_expr_map(functions: List[FunctionSpec], combines: List[CombineSpec]) -> Dict[str, sp.Expr]:
    exprs: Dict[str, sp.Expr] = {}
    for f in functions:
        if not f.id:
            raise ValueError("Eine Funktion hat keine id.")
        if f.id in exprs:
            raise ValueError("Doppelte Funktion id: " + f.id)
        exprs[f.id] = parse_sympy(f.expr)

    remaining = combines[:]
    for _ in range(2000):
        if not remaining:
            return exprs
        progressed = False
        nxt = []
        for c in remaining:
            a, b = c.args
            if a in exprs and b in exprs:
                if c.id in exprs:
                    raise ValueError("Doppelte combine id: " + c.id)
                if c.op == "add":
                    exprs[c.id] = sp.simplify(exprs[a] + exprs[b])
                elif c.op == "sub":
                    exprs[c.id] = sp.simplify(exprs[a] - exprs[b])
                elif c.op == "mul":
                    exprs[c.id] = sp.simplify(exprs[a] * exprs[b])
                elif c.op == "div":
                    exprs[c.id] = sp.simplify(exprs[a] / exprs[b])
                elif c.op == "compose":
                    exprs[c.id] = sp.simplify(exprs[a].subs(_X, exprs[b]))
                else:
                    raise ValueError("Unbekannte op: " + str(c.op))
                progressed = True
            else:
                nxt.append(c)
        if not progressed:
            missing = set()
            for c in nxt:
                for k in c.args:
                    if k not in exprs:
                        missing.add(k)
            raise ValueError("combine verweist auf unbekannte ids: " + ", ".join(sorted(missing)))
        remaining = nxt
    raise ValueError("Konnte combines nicht auflösen (Zyklus?).")



# Layout note:
# We want the *data area* (the grid rectangle) to have an exact physical size so that
# each small square prints as grid_mm (e.g. 5mm). Matplotlib normally reserves margins
# for tick labels, which shrinks the data area and makes squares too small.
# Therefore we create a figure that includes extra margins, and place the Axes with an
# exact size (in inches) corresponding to the desired data area.

DEFAULT_LABEL_MARGIN_CM = 1.0  # space for tick labels around the grid

def make_worksheet_figure(data_w_cm: float, data_h_cm: float, dpi: int) -> tuple[Figure, any, float, float]:
    """Return (fig, ax, fig_w_cm, fig_h_cm) where ax data area is exactly data_w_cm x data_h_cm."""
    m = DEFAULT_LABEL_MARGIN_CM
    fig_w_cm = data_w_cm + 2*m
    fig_h_cm = data_h_cm + 2*m

    fig_w_in = fig_w_cm / 2.54
    fig_h_in = fig_h_cm / 2.54
    fig = Figure(figsize=(fig_w_in, fig_h_in), dpi=int(dpi))

    # Axes rectangle in figure coordinates
    left = m / fig_w_cm
    bottom = m / fig_h_cm
    width = data_w_cm / fig_w_cm
    height = data_h_cm / fig_h_cm
    ax = fig.add_axes([left, bottom, width, height])
    return fig, ax, fig_w_cm, fig_h_cm
# --------------------- Worksheet rendering ---------------------


def fix_svg_units(svg_path: str, width_cm: float, height_cm: float) -> None:
    """
    Matplotlib's SVG backend often writes width/height in pt.
    Browsers/print dialogs may then scale unpredictably.
    This post-process forces physical units (cm) on the root <svg> element.

    Additionally, xml.etree can introduce namespace prefixes like ns0:svg when writing.
    Those prefixes are valid XML but sometimes annoy tools/viewers; we register the SVG
    namespace as the default to keep the output clean (<svg>, <g>, ...).
    """
    # Register common namespaces so ElementTree writes clean SVG without ns0 prefixes.
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ET.register_namespace("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    ET.register_namespace("cc", "http://creativecommons.org/ns#")

    tree = ET.parse(svg_path)
    root = tree.getroot()

    # Force physical size on the root element
    root.set("width", f"{width_cm:.2f}cm")
    root.set("height", f"{height_cm:.2f}cm")

    tree.write(svg_path, encoding="utf-8", xml_declaration=True)

def a4_dimensions_cm(orientation: str) -> Tuple[float, float]:
    w, h = 21.0, 29.7
    if (orientation or "portrait") == "landscape":
        return h, w
    return w, h

def _aligned_start(val: float, step: float) -> float:
    return float(np.floor(val / step) * step)

def _arange_inclusive(a: float, b: float, step: float) -> np.ndarray:
    n = int(np.floor((b - a) / step + 1e-9)) + 1
    return a + step * np.arange(n)

def _pi_label(v: float) -> str:
    # Format v as multiple of pi: -2π, -π/2, 0, π/2, π, 3π/2, 2π ...
    if abs(v) < 1e-12:
        return "0"
    k = v / math.pi
    # snap to quarters to keep labels readable
    denom = 4
    num = int(round(k * denom))
    if num == 0:
        return "0"
    # reduce fraction
    g = math.gcd(abs(num), denom)
    num //= g
    den = denom // g

    sign = "-" if num < 0 else ""
    num_abs = abs(num)

    if den == 1:
        if num_abs == 1:
            return f"{sign}π"
        return f"{sign}{num_abs}π"
    else:
        if num_abs == 1:
            return f"{sign}π/{den}"
        return f"{sign}{num_abs}π/{den}"

def draw_worksheet_axes(ax, spec: PlotSpec) -> None:
    x_min, x_max = spec.x_range
    y_min, y_max = spec.y_range

    cm_per_unit = float(spec.cm_per_unit)
    grid_mm = float(spec.grid_mm)
    if cm_per_unit <= 0:
        raise ValueError("cm_per_unit muss > 0 sein.")
    if grid_mm <= 0:
        raise ValueError("grid_mm muss > 0 sein.")

    grid_cm = grid_mm / 10.0
    minor_step = grid_cm / cm_per_unit
    major_step = minor_step * int(spec.major_every)

    # background
    bg = spec.style.background_color
    ax.figure.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect("equal", adjustable="box")

    # ticks aligned to grid
    x0 = _aligned_start(x_min, minor_step)
    y0 = _aligned_start(y_min, minor_step)
    minor_xticks = _arange_inclusive(x0, x_max + 1e-9, minor_step)
    minor_yticks = _arange_inclusive(y0, y_max + 1e-9, minor_step)

    xM0 = _aligned_start(x_min, major_step)
    yM0 = _aligned_start(y_min, major_step)
    major_xticks = _arange_inclusive(xM0, x_max + 1e-9, major_step)
    major_yticks = _arange_inclusive(yM0, y_max + 1e-9, major_step)

    ax.set_xticks(major_xticks)
    ax.set_yticks(major_yticks)
    ax.set_xticks(minor_xticks, minor=True)
    ax.set_yticks(minor_yticks, minor=True)

    # grid
    ax.grid(which="minor", color=spec.style.grid_minor_color, linewidth=0.35)
    ax.grid(which="major", color=spec.style.grid_major_color, linewidth=0.8)

    # axes lines
    if spec.show_axes:
        ax.axhline(0, color=spec.style.axis_color, linewidth=1.2, zorder=3)
        ax.axvline(0, color=spec.style.axis_color, linewidth=1.2, zorder=3)

    # pi labeling (x only)
    if spec.expert.show_pi_labels:
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, pos: _pi_label(v)))

    ax.tick_params(axis="both", which="major", labelsize=9, color=spec.style.axis_color)
    ax.tick_params(axis="both", which="minor", length=0)

    for spine in ax.spines.values():
        spine.set_color(spec.style.axis_color)
        spine.set_linewidth(0.8)

def export_worksheet(spec: PlotSpec, out_path: str, fmt: str) -> None:
    x_min, x_max = spec.x_range
    y_min, y_max = spec.y_range

    width_cm = (x_max - x_min) * float(spec.cm_per_unit)
    height_cm = (y_max - y_min) * float(spec.cm_per_unit)

    page_w, page_h = a4_dimensions_cm(spec.orientation)
    usable_w = page_w - 2 * float(spec.margin_cm)
    usable_h = page_h - 2 * float(spec.margin_cm)
    if width_cm > usable_w + 1e-6 or height_cm > usable_h + 1e-6:
        raise ValueError(
            "Plot passt nicht auf die Seite.\n"
            + f"Benötigt: {width_cm:.2f}cm x {height_cm:.2f}cm\n"
            + f"Verfügbar: {usable_w:.2f}cm x {usable_h:.2f}cm (A4, Rand {spec.margin_cm:.2f}cm)\n"
            + "Lösung: Range verkleinern oder cm_per_unit reduzieren."
        )

    fig, ax, fig_w_cm, fig_h_cm = make_worksheet_figure(width_cm, height_cm, int(spec.expert.dpi))
    draw_worksheet_axes(ax, spec)

    exprs = build_expr_map(spec.functions, spec.combines)
    ordered: List[str] = [f.id for f in spec.functions] + [c.id for c in spec.combines]

    max_samples = 1200
    for f in spec.functions:
        max_samples = max(max_samples, int(f.samples))
    x_vals = np.linspace(x_min, x_max, max_samples)

    # plot
    for fid in ordered:
        # find per-function style
        col = spec.style.function_color
        lw = spec.style.function_linewidth
        for f in spec.functions:
            if f.id == fid:
                if f.color:
                    col = f.color
                if f.linewidth:
                    lw = float(f.linewidth)
                break
        y_vals = safe_sample(exprs[fid], x_vals)
        ax.plot(x_vals, y_vals, color=col, linewidth=lw, zorder=4)

    fig.savefig(out_path, pad_inches=0.0, facecolor=spec.style.background_color, format=fmt)

    # Force physical cm units into SVG (Matplotlib often writes pt)
    if fmt.lower() == "svg":
        fix_svg_units(out_path, width_cm, height_cm)
# --------------------- Dialogs ---------------------

class FunctionDialog(QDialog):
    def __init__(self, parent=None, initial: Optional[FunctionSpec] = None):
        super().__init__(parent)
        self.setWindowTitle("Funktion")

        self.id_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.expr_edit = QLineEdit()

        self.samples_spin = QSpinBox()
        self.samples_spin.setRange(50, 20000)
        self.samples_spin.setValue(1000)

        self.color_edit = QLineEdit()
        self.color_edit.setPlaceholderText("optional, z.B. #000000")
        self.lw_spin = QDoubleSpinBox()
        self.lw_spin.setRange(0.0, 10.0)
        self.lw_spin.setDecimals(2)
        self.lw_spin.setValue(0.0)
        self.lw_spin.setSingleStep(0.1)

        form = QFormLayout()
        form.addRow("id (z.B. f1)", self.id_edit)
        form.addRow("Label (optional)", self.label_edit)
        form.addRow("Ausdruck", self.expr_edit)
        form.addRow("Samples (Export)", self.samples_spin)
        form.addRow("Farbe (optional)", self.color_edit)
        form.addRow("Linienstärke (optional)", self.lw_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        if initial:
            self.id_edit.setText(initial.id)
            self.label_edit.setText(initial.label)
            self.expr_edit.setText(initial.expr)
            self.samples_spin.setValue(int(initial.samples))
            self.color_edit.setText(initial.color)
            self.lw_spin.setValue(float(initial.linewidth))

    def get_value(self) -> FunctionSpec:
        return FunctionSpec(
            id=self.id_edit.text().strip(),
            label=self.label_edit.text().strip(),
            expr=self.expr_edit.text().strip(),
            samples=int(self.samples_spin.value()),
            color=self.color_edit.text().strip(),
            linewidth=float(self.lw_spin.value()),
        )


class CombineDialog(QDialog):
    def __init__(self, ids: List[str], parent=None, initial: Optional[CombineSpec] = None):
        super().__init__(parent)
        self.setWindowTitle("Combine")

        self.id_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.op_combo = QComboBox()
        self.op_combo.addItems(["add", "sub", "mul", "div", "compose"])

        self.arg1 = QComboBox()
        self.arg2 = QComboBox()
        self.arg1.addItems(ids)
        self.arg2.addItems(ids)

        form = QFormLayout()
        form.addRow("id (z.B. f3)", self.id_edit)
        form.addRow("Label (optional)", self.label_edit)
        form.addRow("op", self.op_combo)
        form.addRow("arg1", self.arg1)
        form.addRow("arg2", self.arg2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        if initial:
            self.id_edit.setText(initial.id)
            self.label_edit.setText(initial.label)
            iop = self.op_combo.findText(initial.op)
            if iop >= 0:
                self.op_combo.setCurrentIndex(iop)
            i1 = self.arg1.findText(initial.args[0])
            i2 = self.arg2.findText(initial.args[1])
            if i1 >= 0:
                self.arg1.setCurrentIndex(i1)
            if i2 >= 0:
                self.arg2.setCurrentIndex(i2)

    def get_value(self) -> CombineSpec:
        return CombineSpec(
            id=self.id_edit.text().strip(),
            label=self.label_edit.text().strip(),
            op=self.op_combo.currentText().strip(),
            args=(self.arg1.currentText().strip(), self.arg2.currentText().strip()),
        )


class ExpertDialog(QDialog):
    def __init__(self, parent=None, spec: Optional[PlotSpec] = None):
        super().__init__(parent)
        self.setWindowTitle("Experten-Einstellungen")

        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setValue(300)

        self.func_color = QLineEdit()
        self.func_lw = QDoubleSpinBox()
        self.func_lw.setRange(0.1, 10.0)
        self.func_lw.setDecimals(2)
        self.func_lw.setSingleStep(0.1)
        self.func_lw.setValue(1.8)

        self.grid_minor = QLineEdit()
        self.grid_major = QLineEdit()
        self.axis_color = QLineEdit()
        self.bg_color = QLineEdit()

        self.pi_labels = QCheckBox("x-Achse als Vielfache von π beschriften")
        self.squares_per_pi = QSpinBox()
        self.squares_per_pi.setRange(1, 50)
        self.squares_per_pi.setValue(8)
        self.apply_pi_scale_btn = QPushButton("Setze Skalierung: π = N Kästchen")
        self.apply_pi_scale_btn.clicked.connect(self._apply_pi_scale)

        form = QFormLayout()
        form.addRow("DPI (Export)", self.dpi)
        form.addRow("Standard Funktionsfarbe", self.func_color)
        form.addRow("Standard Linienstärke", self.func_lw)
        form.addRow("Hintergrund", self.bg_color)
        form.addRow("Grid minor", self.grid_minor)
        form.addRow("Grid major", self.grid_major)
        form.addRow("Achsenfarbe", self.axis_color)
        form.addRow(self.pi_labels)
        form.addRow("N Kästchen pro π", self.squares_per_pi)
        form.addRow("", self.apply_pi_scale_btn)

        self._spec = spec

        # fill from spec
        if spec is not None:
            self.dpi.setValue(int(spec.expert.dpi))
            self.func_color.setText(spec.style.function_color)
            self.func_lw.setValue(float(spec.style.function_linewidth))
            self.bg_color.setText(spec.style.background_color)
            self.grid_minor.setText(spec.style.grid_minor_color)
            self.grid_major.setText(spec.style.grid_major_color)
            self.axis_color.setText(spec.style.axis_color)
            self.pi_labels.setChecked(bool(spec.expert.show_pi_labels))
            self.squares_per_pi.setValue(int(spec.expert.squares_per_pi))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _apply_pi_scale(self):
        # This sets cm_per_unit so that one π equals N small squares (each grid_mm).
        if self._spec is None:
            return
        n = int(self.squares_per_pi.value())
        grid_cm = float(self._spec.grid_mm) / 10.0
        # π spans n squares -> physical length = n*grid_cm
        self._spec.cm_per_unit = (n * grid_cm) / math.pi
        # Align major grid with π: one major step every N small squares
        self._spec.major_every = n
        QMessageBox.information(
            self,
            "π-Skalierung gesetzt",
            f"cm_per_unit wurde gesetzt auf {self._spec.cm_per_unit:.2f}"
            f"major_every wurde auf {n} gesetzt"
            f"(π = {n} Kästchen bei {self._spec.grid_mm:.0f}mm Kästchen)"
        )
    def apply_to(self, spec: PlotSpec):
        spec.expert.dpi = int(self.dpi.value())
        spec.style.function_color = self.func_color.text().strip() or spec.style.function_color
        spec.style.function_linewidth = float(self.func_lw.value())

        spec.style.background_color = self.bg_color.text().strip() or spec.style.background_color
        spec.style.grid_minor_color = self.grid_minor.text().strip() or spec.style.grid_minor_color
        spec.style.grid_major_color = self.grid_major.text().strip() or spec.style.grid_major_color
        spec.style.axis_color = self.axis_color.text().strip() or spec.style.axis_color

        spec.expert.show_pi_labels = bool(self.pi_labels.isChecked())
        spec.expert.squares_per_pi = int(self.squares_per_pi.value())


# --------------------- Preview widget ---------------------

class WorksheetPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

    def clear(self):
        self.fig.clear()
        self.canvas.draw()

    def draw(self, spec: PlotSpec):
        self.fig.clear()
        ax = self.fig.add_axes([0.12, 0.12, 0.85, 0.85])  # stable margins for labels
        draw_worksheet_axes(ax, spec)

        exprs = build_expr_map(spec.functions, spec.combines)
        ordered: List[str] = [f.id for f in spec.functions] + [c.id for c in spec.combines]

        x_min, x_max = spec.x_range
        x_vals = np.linspace(x_min, x_max, 1200)

        for fid in ordered:
            col = spec.style.function_color
            lw = spec.style.function_linewidth
            for f in spec.functions:
                if f.id == fid:
                    if f.color:
                        col = f.color
                    if f.linewidth:
                        lw = float(f.linewidth)
                    break
            y_vals = safe_sample(exprs[fid], x_vals)
            ax.plot(x_vals, y_vals, color=col, linewidth=lw, zorder=4)

        self.canvas.draw()


# --------------------- Main window ---------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Plot Builder (WYSIWYG / 5mm Karo)")

        self.spec = PlotSpec()
        self.spec.functions = [
            FunctionSpec(id="f1", expr="x**2", label="f"),
            FunctionSpec(id="f2", expr="sin(x)", label="g"),
        ]
        self.spec.combines = [CombineSpec(id="f3", op="add", args=("f1", "f2"), label="f+g")]

        # Menu
        open_act = QAction("JSON öffnen…", self)
        open_act.triggered.connect(self.load_json)
        save_act = QAction("JSON speichern…", self)
        save_act.triggered.connect(self.save_json)

        menu = self.menuBar().addMenu("Datei")
        menu.addAction(open_act)
        menu.addAction(save_act)

        splitter = QSplitter(Qt.Horizontal)

        controls = QWidget()
        c_layout = QVBoxLayout()

        # Simple worksheet settings (minimal)
        gb_ws = QGroupBox("Arbeitsblatt")
        fw = QFormLayout()

        self.title_edit = QLineEdit()

        self.orientation = QComboBox()
        self.orientation.addItems(["portrait", "landscape"])

        self.margin_cm = QDoubleSpinBox()
        self.margin_cm.setRange(0, 10)
        self.margin_cm.setDecimals(2)
        self.margin_cm.setValue(self.spec.margin_cm)

        self.cm_per_unit = QDoubleSpinBox()
        self.cm_per_unit.setRange(0.05, 5.0)
        self.cm_per_unit.setDecimals(2)
        self.cm_per_unit.setValue(self.spec.cm_per_unit)

        self.major_every = QSpinBox()
        self.major_every.setRange(1, 20)
        self.major_every.setValue(self.spec.major_every)

        self.show_axes_cb = QCheckBox("Achsen anzeigen")
        self.show_axes_cb.setChecked(True)

        fw.addRow("Titel", self.title_edit)
        fw.addRow("Ausrichtung", self.orientation)
        fw.addRow("Rand (cm)", self.margin_cm)
        fw.addRow("cm pro Einheit", self.cm_per_unit)
        fw.addRow("Major jede n Kästchen", self.major_every)
        fw.addRow("", self.show_axes_cb)

        gb_ws.setLayout(fw)
        c_layout.addWidget(gb_ws)

        # Range settings
        gb_rng = QGroupBox("Bereich (WYSIWYG)")
        fr = QFormLayout()
        self.xmin = QDoubleSpinBox()
        self.xmax = QDoubleSpinBox()
        self.ymin = QDoubleSpinBox()
        self.ymax = QDoubleSpinBox()
        for sb in (self.xmin, self.xmax, self.ymin, self.ymax):
            sb.setRange(-1e6, 1e6)
            sb.setDecimals(2)
        self.xmin.setValue(self.spec.x_range[0])
        self.xmax.setValue(self.spec.x_range[1])
        self.ymin.setValue(self.spec.y_range[0])
        self.ymax.setValue(self.spec.y_range[1])

        rowx = QHBoxLayout()
        rowx.addWidget(self.xmin)
        rowx.addWidget(QLabel("bis"))
        rowx.addWidget(self.xmax)
        rowxw = QWidget()
        rowxw.setLayout(rowx)

        rowy = QHBoxLayout()
        rowy.addWidget(self.ymin)
        rowy.addWidget(QLabel("bis"))
        rowy.addWidget(self.ymax)
        rowyw = QWidget()
        rowyw.setLayout(rowy)

        fr.addRow("x_range", rowxw)
        fr.addRow("y_range", rowyw)
        gb_rng.setLayout(fr)
        c_layout.addWidget(gb_rng)

        # Functions
        gb_fun = QGroupBox("Funktionen")
        vf = QVBoxLayout()
        self.fun_table = QTableWidget(0, 5)
        self.fun_table.setHorizontalHeaderLabels(["id", "label", "expr", "farbe", "lw"])
        self.fun_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.fun_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.fun_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.fun_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.fun_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.fun_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fun_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        fbtn = QHBoxLayout()
        self.add_fun_btn = QPushButton("＋")
        self.edit_fun_btn = QPushButton("Bearbeiten")
        self.del_fun_btn = QPushButton("Entfernen")
        fbtn.addWidget(self.add_fun_btn)
        fbtn.addWidget(self.edit_fun_btn)
        fbtn.addWidget(self.del_fun_btn)

        self.add_fun_btn.clicked.connect(self.add_function)
        self.edit_fun_btn.clicked.connect(self.edit_function)
        self.del_fun_btn.clicked.connect(self.delete_function)

        vf.addWidget(self.fun_table)
        vf.addLayout(fbtn)
        gb_fun.setLayout(vf)
        c_layout.addWidget(gb_fun)

        # Combines
        gb_com = QGroupBox("Combines")
        vc = QVBoxLayout()
        self.com_table = QTableWidget(0, 5)
        self.com_table.setHorizontalHeaderLabels(["id", "op", "arg1", "arg2", "label"])
        self.com_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.com_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.com_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        cbtn = QHBoxLayout()
        self.add_com_btn = QPushButton("＋")
        self.edit_com_btn = QPushButton("Bearbeiten")
        self.del_com_btn = QPushButton("Entfernen")
        cbtn.addWidget(self.add_com_btn)
        cbtn.addWidget(self.edit_com_btn)
        cbtn.addWidget(self.del_com_btn)

        self.add_com_btn.clicked.connect(self.add_combine)
        self.edit_com_btn.clicked.connect(self.edit_combine)
        self.del_com_btn.clicked.connect(self.delete_combine)

        vc.addWidget(self.com_table)
        vc.addLayout(cbtn)
        gb_com.setLayout(vc)
        c_layout.addWidget(gb_com)

        # Actions row
        row = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.clicked.connect(self.update_preview)
        self.save_bundle_btn = QPushButton("Speichern (JSON + PDF + SVG)")
        self.save_bundle_btn.clicked.connect(self.save_bundle)
        self.expert_btn = QPushButton("Experte…")
        self.expert_btn.clicked.connect(self.open_expert)
        self.help_btn = QPushButton("Hilfe")
        self.help_btn.clicked.connect(self.show_help)
        row.addWidget(self.preview_btn)
        row.addWidget(self.save_bundle_btn)
        row.addWidget(self.expert_btn)
        row.addWidget(self.help_btn)
        c_layout.addLayout(row)

        self.fit_label = QLabel("")
        self.fit_label.setWordWrap(True)
        c_layout.addWidget(self.fit_label)

        c_layout.addStretch(1)
        controls.setLayout(c_layout)

        self.preview = WorksheetPreview()
        splitter.addWidget(controls)
        splitter.addWidget(self.preview)
        splitter.setSizes([560, 780])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Bereit")
        self.refresh_tables()
        self.sync_widgets_from_spec()
        self.update_preview()

    # -------- helpers --------
    def _error_box(self, title: str, exc: Exception) -> None:
        msg = str(exc) + "\n\nDetails:\n" + traceback.format_exc()
        QMessageBox.critical(self, title, msg)

    def sync_spec_from_widgets(self) -> None:
        self.spec.title = self.title_edit.text().strip()
        self.spec.orientation = self.orientation.currentText().strip()
        self.spec.margin_cm = float(self.margin_cm.value())
        self.spec.cm_per_unit = float(self.cm_per_unit.value())
        self.spec.major_every = int(self.major_every.value())
        self.spec.show_axes = bool(self.show_axes_cb.isChecked())

        self.spec.x_range = (float(self.xmin.value()), float(self.xmax.value()))
        self.spec.y_range = (float(self.ymin.value()), float(self.ymax.value()))
        if self.spec.x_range[1] <= self.spec.x_range[0]:
            raise ValueError("x_range: max muss größer als min sein.")
        if self.spec.y_range[1] <= self.spec.y_range[0]:
            raise ValueError("y_range: max muss größer als min sein.")

    def sync_widgets_from_spec(self) -> None:
        self.title_edit.setText(self.spec.title)
        self.orientation.setCurrentText(self.spec.orientation)
        self.margin_cm.setValue(float(self.spec.margin_cm))
        self.cm_per_unit.setValue(float(self.spec.cm_per_unit))
        self.major_every.setValue(int(self.spec.major_every))
        self.show_axes_cb.setChecked(bool(self.spec.show_axes))

        self.xmin.setValue(self.spec.x_range[0])
        self.xmax.setValue(self.spec.x_range[1])
        self.ymin.setValue(self.spec.y_range[0])
        self.ymax.setValue(self.spec.y_range[1])

    def refresh_tables(self) -> None:
        self.fun_table.setRowCount(0)
        for f in self.spec.functions:
            r = self.fun_table.rowCount()
            self.fun_table.insertRow(r)
            self.fun_table.setItem(r, 0, QTableWidgetItem(f.id))
            self.fun_table.setItem(r, 1, QTableWidgetItem(f.label))
            self.fun_table.setItem(r, 2, QTableWidgetItem(f.expr))
            self.fun_table.setItem(r, 3, QTableWidgetItem(f.color))
            self.fun_table.setItem(r, 4, QTableWidgetItem("" if not f.linewidth else f"{f.linewidth:.2f}"))

        self.com_table.setRowCount(0)
        for c in self.spec.combines:
            r = self.com_table.rowCount()
            self.com_table.insertRow(r)
            self.com_table.setItem(r, 0, QTableWidgetItem(c.id))
            self.com_table.setItem(r, 1, QTableWidgetItem(c.op))
            self.com_table.setItem(r, 2, QTableWidgetItem(c.args[0]))
            self.com_table.setItem(r, 3, QTableWidgetItem(c.args[1]))
            self.com_table.setItem(r, 4, QTableWidgetItem(c.label))

    def _selected_row(self, table: QTableWidget) -> int:
        rows = table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    # -------- CRUD --------
    def add_function(self):
        dlg = FunctionDialog(self)
        if dlg.exec() == QDialog.Accepted:
            f = dlg.get_value()
            try:
                if not f.id:
                    raise ValueError("id fehlt.")
                parse_sympy(f.expr)
            except Exception as e:
                self._error_box("Ungültige Funktion", e)
                return
            if self._id_exists(f.id):
                QMessageBox.critical(self, "Fehler", "id existiert bereits: " + f.id)
                return
            self.spec.functions.append(f)
            self.refresh_tables()
            self.update_preview()

    def edit_function(self):
        idx = self._selected_row(self.fun_table)
        if idx < 0:
            return
        dlg = FunctionDialog(self, self.spec.functions[idx])
        if dlg.exec() == QDialog.Accepted:
            f = dlg.get_value()
            try:
                if not f.id:
                    raise ValueError("id fehlt.")
                parse_sympy(f.expr)
            except Exception as e:
                self._error_box("Ungültige Funktion", e)
                return
            # uniqueness
            existing = {x.id for i, x in enumerate(self.spec.functions) if i != idx}
            existing |= {x.id for x in self.spec.combines}
            if f.id in existing:
                QMessageBox.critical(self, "Fehler", "id existiert bereits: " + f.id)
                return

            old_id = self.spec.functions[idx].id
            self.spec.functions[idx] = f
            # update combines referencing old id
            if old_id != f.id:
                updated = []
                for c in self.spec.combines:
                    a, b = c.args
                    if a == old_id:
                        a = f.id
                    if b == old_id:
                        b = f.id
                    updated.append(CombineSpec(id=c.id, op=c.op, args=(a, b), label=c.label))
                self.spec.combines = updated

            self.refresh_tables()
            self.update_preview()

    def delete_function(self):
        idx = self._selected_row(self.fun_table)
        if idx < 0:
            return
        fid = self.spec.functions[idx].id
        self.spec.functions.pop(idx)
        self.spec.combines = [c for c in self.spec.combines if fid not in c.args]
        self.refresh_tables()
        self.update_preview()

    def add_combine(self):
        ids = [f.id for f in self.spec.functions] + [c.id for c in self.spec.combines]
        if len(ids) < 2:
            QMessageBox.information(self, "Hinweis", "Du brauchst mindestens zwei Funktionen/IDs.")
            return
        dlg = CombineDialog(ids, self)
        if dlg.exec() == QDialog.Accepted:
            c = dlg.get_value()
            if not c.id:
                QMessageBox.critical(self, "Fehler", "Combine braucht eine id.")
                return
            if self._id_exists(c.id):
                QMessageBox.critical(self, "Fehler", "id existiert bereits: " + c.id)
                return
            self.spec.combines.append(c)
            self.refresh_tables()
            self.update_preview()

    def edit_combine(self):
        idx = self._selected_row(self.com_table)
        if idx < 0:
            return
        ids = [f.id for f in self.spec.functions] + [c.id for c in self.spec.combines]
        dlg = CombineDialog(ids, self, self.spec.combines[idx])
        if dlg.exec() == QDialog.Accepted:
            c = dlg.get_value()
            if not c.id:
                QMessageBox.critical(self, "Fehler", "Combine braucht eine id.")
                return
            existing = {x.id for x in self.spec.functions}
            existing |= {x.id for i, x in enumerate(self.spec.combines) if i != idx}
            if c.id in existing:
                QMessageBox.critical(self, "Fehler", "id existiert bereits: " + c.id)
                return
            self.spec.combines[idx] = c
            self.refresh_tables()
            self.update_preview()

    def delete_combine(self):
        idx = self._selected_row(self.com_table)
        if idx < 0:
            return
        self.spec.combines.pop(idx)
        self.refresh_tables()
        self.update_preview()

    def _id_exists(self, new_id: str) -> bool:
        return any(x.id == new_id for x in self.spec.functions) or any(x.id == new_id for x in self.spec.combines)

    # -------- Expert / Help --------
    def open_expert(self):
        dlg = ExpertDialog(self, self.spec)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_to(self.spec)
            # update visible cm_per_unit if π-scale button changed it
            self.sync_widgets_from_spec()
            self.update_preview()

    def show_help(self):
        text = (
            "Eingabe-Syntax (SymPy-like):\n\n"
            "Potenz:\n"
            "  x**2   bedeutet x²\n"
            "  x**(1/2) oder sqrt(x)   bedeutet √x\n\n"
            "Multiplikation:\n"
            "  2*x   (nicht 2x)\n\n"
            "Trigonometrie:\n"
            "  sin(x), cos(x), tan(x)\n\n"
            "Exponential/Log:\n"
            "  exp(x), log(x)\n\n"
            "Konstanten:\n"
            "  pi, E\n\n"
            "Beispiele:\n"
            "  sin(x) + 0.5*x\n"
            "  (x-2)**2 - 3\n"
            "  exp(-x)*sin(x)\n\n"
            "Hinweis: ^ wird als Potenz akzeptiert (x^2)."
        )
        QMessageBox.information(self, "Hilfe: Funktions-Eingabe", text)

    # -------- Preview / Save --------
    def update_preview(self):
        try:
            self.sync_spec_from_widgets()
            self.preview.draw(self.spec)
            self.fit_label.setText(self._fit_text())
            self.statusBar().showMessage("Preview aktualisiert")
        except Exception as e:
            self.preview.clear()
            self._error_box("Preview Fehler", e)

    def _fit_text(self) -> str:
        x_min, x_max = self.spec.x_range
        y_min, y_max = self.spec.y_range
        data_w_cm = (x_max - x_min) * float(self.spec.cm_per_unit)
        data_h_cm = (y_max - y_min) * float(self.spec.cm_per_unit)
        width_cm = data_w_cm + 2*DEFAULT_LABEL_MARGIN_CM
        height_cm = data_h_cm + 2*DEFAULT_LABEL_MARGIN_CM

        page_w, page_h = a4_dimensions_cm(self.spec.orientation)
        usable_w = page_w - 2 * float(self.spec.margin_cm)
        usable_h = page_h - 2 * float(self.spec.margin_cm)

        ok = (width_cm <= usable_w + 1e-6) and (height_cm <= usable_h + 1e-6)
        msg = (
            f"Plot-Datenfläche: {data_w_cm:.2f}cm × {data_h_cm:.2f}cm\n"            f"Plot inkl. Beschriftungsrand: {width_cm:.2f}cm × {height_cm:.2f}cm\n"
            f"A4 nutzbar: {usable_w:.2f}cm × {usable_h:.2f}cm (Rand {self.spec.margin_cm:.2f}cm)\n"
        )
        msg += "✅ Passt auf die Seite." if ok else "⚠️ Passt NICHT auf die Seite."
        return msg

    def save_bundle(self):
        try:
            self.sync_spec_from_widgets()
        except Exception as e:
            self._error_box("Speichern Fehler", e)
            return

        default_name = "plot"
        if self.spec.title.strip():
            import re as _re
            default_name = _re.sub(r"[^A-Za-z0-9_\-]+", "_", self.spec.title.strip()).strip("_") or "plot"

        path, _ = QFileDialog.getSaveFileName(self, "Speichern (JSON + PDF + SVG)", default_name, "Plot (*.json)")
        if not path:
            return
        base = path[:-5] if path.lower().endswith(".json") else path
        json_path = base + ".json"
        svg_path = base + ".svg"
        pdf_path = base + ".pdf"

        try:
            payload = self.spec.to_json_dict()
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            export_worksheet(self.spec, pdf_path, fmt="pdf")

            export_worksheet(self.spec, svg_path, fmt="svg")

            self.statusBar().showMessage("Gespeichert: " + json_path + ", " + pdf_path + " und " + svg_path)
            QMessageBox.information(
                self,
                "Gespeichert",
                "Erstellt:\n" + json_path + "\n" + pdf_path + "\n" + svg_path +
                "\n\nHinweis: Für maßhaltige Ausdrucke bitte bevorzugt die PDF drucken (100% / 'Tatsächliche Größe')."
            )
        except Exception as e:
            self._error_box("Speichern Fehler", e)

    # -------- JSON IO --------
    def save_json(self):
        try:
            self.sync_spec_from_widgets()
        except Exception as e:
            self._error_box("JSON Fehler", e)
            return
        path, _ = QFileDialog.getSaveFileName(self, "JSON speichern", "plot.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.spec.to_json_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._error_box("JSON Fehler", e)

    def load_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "JSON öffnen", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            # simple load: only what we wrote (backward friendly)
            self._load_from_dict(d)
            self.refresh_tables()
            self.sync_widgets_from_spec()
            self.update_preview()
        except Exception as e:
            self._error_box("JSON Fehler", e)

    def _load_from_dict(self, d: dict):
        self.spec.title = d.get("title", "")
        ax = d.get("axes", {})
        xr = ax.get("x_range", [-10, 10])
        yr = ax.get("y_range", [-8, 8])
        self.spec.x_range = (float(xr[0]), float(xr[1]))
        self.spec.y_range = (float(yr[0]), float(yr[1]))
        self.spec.show_axes = bool(ax.get("show_axes", True))
        self.spec.expert.show_pi_labels = bool(ax.get("pi_labels", False))

        paper = d.get("paper", {})
        self.spec.orientation = paper.get("orientation", "portrait")
        self.spec.margin_cm = float(paper.get("margin_cm", 1.5))
        self.spec.grid_mm = float(paper.get("grid_mm", 5.0))
        self.spec.cm_per_unit = float(paper.get("cm_per_unit", 0.5))
        self.spec.major_every = int(paper.get("major_every", 5))
        self.spec.expert.dpi = int(paper.get("dpi", 300))

        style = paper.get("style", {})
        self.spec.style.background_color = style.get("background_color", self.spec.style.background_color)
        self.spec.style.grid_minor_color = style.get("grid_minor_color", self.spec.style.grid_minor_color)
        self.spec.style.grid_major_color = style.get("grid_major_color", self.spec.style.grid_major_color)
        self.spec.style.axis_color = style.get("axis_color", self.spec.style.axis_color)

        render = d.get("render", {})
        self.spec.style.function_color = render.get("function_color", self.spec.style.function_color)
        self.spec.style.function_linewidth = float(render.get("function_linewidth", self.spec.style.function_linewidth))

        self.spec.functions = []
        for f in d.get("functions", []):
            st = f.get("style", {})
            self.spec.functions.append(
                FunctionSpec(
                    id=str(f.get("id", "")),
                    expr=str(f.get("expr", "")),
                    label=str(f.get("label", "")),
                    samples=int(f.get("samples", 1000)),
                    color=str(st.get("color", "")),
                    linewidth=float(st.get("linewidth", 0.0)) if st.get("linewidth", 0.0) else 0.0,
                )
            )
        self.spec.combines = []
        for c in d.get("combines", []):
            args = c.get("args", ["", ""])
            self.spec.combines.append(
                CombineSpec(
                    id=str(c.get("id", "")),
                    op=str(c.get("op", "add")),
                    args=(str(args[0]), str(args[1])),
                    label=str(c.get("label", "")),
                )
            )


def main():
    app = QApplication([])
    w = MainWindow()
    w.resize(1500, 920)
    w.show()
    app.exec()

if __name__ == "__main__":
    main()
