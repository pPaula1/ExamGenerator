#!/usr/bin/env python3
"""
Render a header JSON to LaTeX/PDF.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from schema_utils import validate_instance


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def latex_escape(text: str) -> str:
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
    return "".join(replacements.get(ch, ch) for ch in str(text))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_ref(base_file: Path, ref: str) -> Path:
    p = Path(ref)
    if p.is_absolute():
        return p
    # Default: resolve relative to the JSON file itself.
    direct = (base_file.parent / p).resolve()
    if direct.exists():
        return direct

    # Fallback for copied/temp header JSON files (e.g. rendered from out_pdf):
    # interpret refs as if they came from data/headers.
    from_headers = (PROJECT_ROOT / "data" / "headers" / p).resolve()
    if from_headers.exists():
        return from_headers

    # Keep original resolved value for downstream error handling.
    return direct


def resolve_logo(header_file: Path, header_data: dict[str, Any], school_data: dict[str, Any] | None) -> Path | None:
    explicit = str(header_data.get("logo_path", "")).strip()
    if explicit:
        p = resolve_ref(header_file, explicit)
        if p.exists():
            return p

    if school_data:
        logo = school_data.get("logo") or {}
        lp = str(logo.get("path", "")).strip()
        if lp:
            school_ref = str(header_data.get("school_info_ref", "")).strip()
            if school_ref:
                school_file = resolve_ref(header_file, school_ref)
                candidate = (school_file.parent / lp).resolve()
                if candidate.exists():
                    return candidate
            candidate = (PROJECT_ROOT / lp).resolve()
            if candidate.exists():
                return candidate
    return None


def apply_placeholders(lines: list[str], ctx: dict[str, str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        s = str(line)
        for k, v in ctx.items():
            s = s.replace("{{" + k + "}}", v)
        out.append(s)
    return out


def strip_redundant_info_lines(lines: list[str]) -> list[str]:
    # These fields are already rendered in dedicated header cells.
    redundant_prefixes = (
        "name:",
        "arbeitszeit:",
    )
    cleaned: list[str] = []
    for line in lines:
        s = str(line).strip()
        low = s.lower()
        if any(low.startswith(prefix) for prefix in redundant_prefixes):
            continue
        cleaned.append(s)
    return cleaned


def to_latex_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    return r" \\ ".join(latex_escape(x) for x in lines)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "ja", "on"}:
            return True
        if v in {"false", "0", "no", "nein", "off", ""}:
            return False
    return bool(value)


def merge_with_school_defaults(header_data: dict[str, Any], school_data: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(header_data)
    if not school_data:
        return merged

    if not merged.get("school_name") and school_data.get("name"):
        merged["school_name"] = school_data["name"]

    defaults = school_data.get("defaults") or {}
    for key in ("subject", "class_name", "teacher"):
        if not merged.get(key) and defaults.get(key):
            merged[key] = defaults[key]
    return merged


def load_school_from_header_ref(header_file: Path, header_data: dict[str, Any]) -> dict[str, Any] | None:
    school_ref = str(header_data.get("school_info_ref", "")).strip()
    if school_ref:
        school_file = resolve_ref(header_file, school_ref)
        if school_file.exists():
            return load_json(school_file)
    return None


def build_header_block_tex(
    header_file: Path,
    header_data: dict[str, Any],
    points_total: str,
    school_data_override: dict[str, Any] | None = None,
) -> str:
    school_data = school_data_override if school_data_override is not None else load_school_from_header_ref(header_file, header_data)

    data = merge_with_school_defaults(header_data, school_data)

    layout = data.get("layout") or {}
    show_logo = bool(layout.get("show_logo", True))
    logo_width = float(layout.get("logo_width_cm", 3.0))

    logo_path = resolve_logo(header_file, data, school_data)
    logo_tex = ""
    if show_logo and logo_path and logo_path.exists():
        logo_tex = rf"\includegraphics[width={logo_width:.2f}cm]{{{str(logo_path).replace('\\', '/')}}}"

    title = latex_escape(data.get("title", ""))
    subtitle = latex_escape(data.get("subtitle", ""))
    school_name = latex_escape(data.get("school_name", ""))
    class_name = latex_escape(data.get("class_name", ""))
    subject = latex_escape(data.get("subject", ""))
    allowed_materials = latex_escape(data.get("allowed_materials", ""))
    show_nta_measures = as_bool(data.get("show_nta_measures", False))
    show_time_bonus_percent = as_bool(data.get("show_time_bonus_percent", False))
    teacher = latex_escape(data.get("teacher", ""))
    date = latex_escape(data.get("date", ""))
    duration = str(data.get("duration_min", ""))

    left_lines = apply_placeholders(data.get("left_lines") or [], {"points_total": points_total})
    right_lines = apply_placeholders(data.get("right_lines") or [], {"points_total": points_total})
    left_lines = strip_redundant_info_lines(left_lines)
    right_lines = strip_redundant_info_lines(right_lines)
    left_block = to_latex_lines(left_lines)
    right_block = to_latex_lines(right_lines)
    duration_title_line = ""
    if duration:
        duration_title_line = rf" \\[0.2em] \small \textbf{{Arbeitszeit: {latex_escape(duration)} min}}"

    nta_row: list[str] = []
    if show_nta_measures and show_time_bonus_percent:
        nta_row = [
            r"\multicolumn{3}{|p{0.96\linewidth}|}{"
            + r"\begin{tabular}[t]{@{}p{0.24\linewidth}|p{0.24\linewidth}|p{0.24\linewidth}|p{0.24\linewidth}@{}}"
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{NTA-Ma\ss nahme}\end{minipage} & "
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{Beansprucht:}\\[-0.02em]\begin{tabular}[t]{@{}l@{}}\cb\ Ja\\\cb\ Nein\end{tabular}\end{minipage} & "
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{Zeitzuschlag in Prozent}\end{minipage} & "
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{Beansprucht:}\\[-0.02em]\begin{tabular}[t]{@{}l@{}}\cb\ Ja, Minuten \rule{0.24\linewidth}{0.4pt}\\\cb\ Nein\end{tabular}\end{minipage}"
            + r"\end{tabular}"
            + r"} \\",
            r"\hline",
        ]
    elif show_nta_measures:
        nta_row = [
            r"\multicolumn{3}{|p{0.96\linewidth}|}{"
            + r"\begin{tabular}[t]{@{}p{0.48\linewidth}|p{0.48\linewidth}@{}}"
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{NTA-Ma\ss nahme}\end{minipage} & "
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{Beansprucht:}\\[-0.02em]\begin{tabular}[t]{@{}l@{}}\cb\ Ja\\\cb\ Nein\end{tabular}\end{minipage}"
            + r"\end{tabular}"
            + r"} \\",
            r"\hline",
        ]
    elif show_time_bonus_percent:
        nta_row = [
            r"\multicolumn{3}{|p{0.96\linewidth}|}{"
            + r"\begin{tabular}[t]{@{}p{0.48\linewidth}|p{0.48\linewidth}@{}}"
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{Zeitzuschlag in Prozent}\end{minipage} & "
            + r"\begin{minipage}[t][1.35cm][t]{\linewidth}\vspace*{0pt}\footnotesize \textbf{Beansprucht:}\\[-0.02em]\begin{tabular}[t]{@{}l@{}}\cb\ Ja, Minuten \rule{0.24\linewidth}{0.4pt}\\\cb\ Nein\end{tabular}\end{minipage}"
            + r"\end{tabular}"
            + r"} \\",
            r"\hline",
        ]

    return "\n".join(
        [
            r"\noindent",
            r"\begin{tabular}{|p{0.21\linewidth}|p{0.55\linewidth}|p{0.20\linewidth}|}",
            r"\hline",
            r"\begin{minipage}[c][2.8cm][c]{\linewidth}\centering "
            + (logo_tex if logo_tex else r"\textbf{Logo}")
            + r"\end{minipage} & "
            + r"\begin{minipage}[c][2.8cm][c]{\linewidth}\centering \textbf{\Large "
            + title
            + r"}"
            + (rf" \\[0.25em] \normalsize {subtitle}" if subtitle else "")
            + duration_title_line
            + r"\end{minipage} & "
            + r"\begin{minipage}[c][2.8cm][c]{\linewidth}\centering \textbf{Punkte} \\[0.35em] \Huge "
            + latex_escape(points_total)
            + r"\end{minipage} \\",
            r"\hline",
            r"\multicolumn{3}{|p{0.96\linewidth}|}{"
            + r"\begin{tabular}{@{}p{0.60\linewidth}|p{0.40\linewidth}@{}}"
            + r"\begin{minipage}[c][2.2cm][c]{\linewidth}"
            + school_name
            + r" \\[0.30em] \textbf{Fach:} "
            + subject
            + r"\end{minipage} & "
            + r"\begin{minipage}[c][2.2cm][c]{\linewidth}\textbf{Datum:} "
            + date
            + r" \\[0.28em] \textbf{Klasse:} "
            + class_name
            + r" \\[0.28em] \textbf{Lehrkraft:} "
            + teacher
            + r"\end{minipage}"
            + r"\end{tabular}"
            + r"} \\",
            r"\hline",
            r"\multicolumn{3}{|p{0.96\linewidth}|}{"
            + r"\begin{tabular}{@{}p{0.60\linewidth}|p{0.40\linewidth}@{}}"
            + r"\begin{minipage}[t][2.2cm][t]{\linewidth}"
            + r"\textbf{Name:}"
            + r"\vspace*{\fill}\\"
            + r"\rule{0.94\linewidth}{0.4pt}\\[0.05cm]"
            + r"\end{minipage} & "
            + r"\begin{minipage}[t][2.2cm][t]{\linewidth}"
            + r"\textbf{Unterschrift Erziehungsberechtigter:}"
            + r"\vspace*{\fill}\\"
            + r"\rule{0.94\linewidth}{0.4pt}\\[0.05cm]"
            + r"\end{minipage}"
            + r"\end{tabular}"
            + r"} \\",
            r"\hline",
            *nta_row,
            r"\begin{minipage}[t][1.8cm][t]{\linewidth}\textbf{Zugelassene Hilfsmittel:} "
            + (allowed_materials if allowed_materials else r"-")
            + r"\end{minipage} & "
            + r"\multicolumn{2}{p{0.79\linewidth}|}{\begin{minipage}[t][1.8cm][t]{\linewidth}\vspace*{\fill}\textbf{Korrektur:} Punkte: \rule{0.14\linewidth}{0.4pt}\hspace{1.0em} Note: \rule{0.14\linewidth}{0.4pt}\\[0.2cm]\end{minipage}} \\",
            r"\hline",
            r"\end{tabular}",
            "",
        ]
    )


def build_header_tex(header_file: Path, header_data: dict[str, Any], points_total: str) -> str:
    block = build_header_block_tex(header_file, header_data, points_total)
    return "\n".join(
        [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[ngerman]{babel}",
            r"\usepackage{geometry}",
            r"\usepackage{graphicx}",
            r"\usepackage{array}",
            r"\geometry{margin=2cm}",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\tabcolsep}{6pt}",
            r"\renewcommand{\arraystretch}{1.0}",
            r"\newcommand{\cb}{\raisebox{0pt}[0.85em][0pt]{\fbox{\rule{0pt}{0.7em}\rule{0.7em}{0pt}}}}",
            r"\begin{document}",
            block,
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
    subprocess.run(cmd, check=True)
    subprocess.run(cmd, check=True)
    print(f"PDF created: {out_dir / (tex_file.stem + '.pdf')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Header JSON file")
    ap.add_argument("--output-dir", default="out_pdf", help="Output directory for tex/pdf")
    ap.add_argument("--name", default="header", help="Base name for generated tex/pdf")
    ap.add_argument("--points-total", default="0", help="Value for {{points_total}} and points box")
    ap.add_argument("--no-compile", action="store_true", help="Only generate .tex, do not run pdflatex")
    args = ap.parse_args()

    header_file = Path(args.input).resolve()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    data = load_json(header_file)
    validate_instance(data, "header", label=str(header_file))
    tex_content = build_header_tex(header_file, data, str(args.points_total))
    tex_file = out_dir / f"{args.name}.tex"
    tex_file.write_text(tex_content, encoding="utf-8")
    print(f"LaTeX written: {tex_file}")

    if not args.no_compile:
        compile_pdf(tex_file, out_dir)


if __name__ == "__main__":
    main()
