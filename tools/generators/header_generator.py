#!/usr/bin/env python3
"""
Simple GUI to create/edit header JSON files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = PROJECT_ROOT / "schemas" / "header" / "header.schema.json"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "headers"


def slugify_id(text: str) -> str:
    s = text.lower().strip()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if len(s) < 3:
        s = (s + "_hdr")[:8]
    return s[:65]


def parse_int(raw: str, field_name: str, min_value: int = 0) -> int:
    v = raw.strip()
    if not v:
        raise ValueError(f"Feld '{field_name}' darf nicht leer sein.")
    n = int(v)
    if n < min_value:
        raise ValueError(f"Feld '{field_name}' muss >= {min_value} sein.")
    return n


def parse_float(raw: str, field_name: str, min_value: float = 0.0) -> float:
    v = raw.strip().replace(",", ".")
    if not v:
        raise ValueError(f"Feld '{field_name}' darf nicht leer sein.")
    n = float(v)
    if n < min_value:
        raise ValueError(f"Feld '{field_name}' muss >= {min_value} sein.")
    return n


def make_validator(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


class HeaderGeneratorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Header Generator")
        self.root.geometry("1100x820")

        self.current_json: dict | None = None

        self.id_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.subtitle_var = tk.StringVar()
        self.school_name_var = tk.StringVar()
        self.class_name_var = tk.StringVar()
        self.subject_var = tk.StringVar()
        self.teacher_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.duration_min_var = tk.StringVar(value="60")
        self.logo_path_var = tk.StringVar()
        self.school_info_ref_var = tk.StringVar()

        self.show_logo_var = tk.BooleanVar(value=True)
        self.show_border_var = tk.BooleanVar(value=True)
        self.header_height_cm_var = tk.StringVar(value="4.0")
        self.logo_width_cm_var = tk.StringVar(value="3.0")

        self._build_ui()

    def _build_ui(self) -> None:
        form = tk.LabelFrame(self.root, text="Header-Daten")
        form.pack(fill="x", padx=8, pady=8)

        r = 0
        tk.Label(form, text="Titel*").grid(row=r, column=0, sticky="w", padx=6, pady=5)
        tk.Entry(form, textvariable=self.title_var, width=55).grid(row=r, column=1, sticky="we", padx=6, pady=5)
        tk.Button(form, text="ID aus Titel", command=self.fill_id_from_title).grid(row=r, column=2, padx=6, pady=5)
        tk.Label(form, text="ID*").grid(row=r, column=3, sticky="e", padx=6, pady=5)
        tk.Entry(form, textvariable=self.id_var, width=28).grid(row=r, column=4, sticky="w", padx=6, pady=5)

        r += 1
        tk.Label(form, text="Untertitel").grid(row=r, column=0, sticky="w", padx=6, pady=5)
        tk.Entry(form, textvariable=self.subtitle_var, width=55).grid(row=r, column=1, sticky="we", padx=6, pady=5)
        tk.Label(form, text="Datum").grid(row=r, column=3, sticky="e", padx=6, pady=5)
        tk.Entry(form, textvariable=self.date_var, width=28).grid(row=r, column=4, sticky="w", padx=6, pady=5)

        r += 1
        tk.Label(form, text="Schule").grid(row=r, column=0, sticky="w", padx=6, pady=5)
        tk.Entry(form, textvariable=self.school_name_var, width=55).grid(row=r, column=1, sticky="we", padx=6, pady=5)
        tk.Label(form, text="Klasse").grid(row=r, column=3, sticky="e", padx=6, pady=5)
        tk.Entry(form, textvariable=self.class_name_var, width=28).grid(row=r, column=4, sticky="w", padx=6, pady=5)

        r += 1
        tk.Label(form, text="Fach").grid(row=r, column=0, sticky="w", padx=6, pady=5)
        tk.Entry(form, textvariable=self.subject_var, width=55).grid(row=r, column=1, sticky="we", padx=6, pady=5)
        tk.Label(form, text="Lehrkraft").grid(row=r, column=3, sticky="e", padx=6, pady=5)
        tk.Entry(form, textvariable=self.teacher_var, width=28).grid(row=r, column=4, sticky="w", padx=6, pady=5)

        r += 1
        tk.Label(form, text="Arbeitszeit (min)").grid(row=r, column=0, sticky="w", padx=6, pady=5)
        tk.Entry(form, textvariable=self.duration_min_var, width=12).grid(row=r, column=1, sticky="w", padx=6, pady=5)

        r += 1
        tk.Label(form, text="school_info_ref").grid(row=r, column=0, sticky="w", padx=6, pady=5)
        tk.Entry(form, textvariable=self.school_info_ref_var, width=70).grid(row=r, column=1, columnspan=3, sticky="we", padx=6, pady=5)
        tk.Button(form, text="Datei waehlen", command=self.choose_school_info).grid(row=r, column=4, padx=6, pady=5, sticky="w")

        r += 1
        tk.Label(form, text="logo_path").grid(row=r, column=0, sticky="w", padx=6, pady=5)
        tk.Entry(form, textvariable=self.logo_path_var, width=70).grid(row=r, column=1, columnspan=3, sticky="we", padx=6, pady=5)
        tk.Button(form, text="Datei waehlen", command=self.choose_logo).grid(row=r, column=4, padx=6, pady=5, sticky="w")

        r += 1
        layout = tk.LabelFrame(form, text="Layout")
        layout.grid(row=r, column=0, columnspan=5, sticky="we", padx=6, pady=6)
        tk.Checkbutton(layout, text="Logo anzeigen", variable=self.show_logo_var).grid(row=0, column=0, padx=6, pady=5, sticky="w")
        tk.Checkbutton(layout, text="Rahmen anzeigen", variable=self.show_border_var).grid(row=0, column=1, padx=6, pady=5, sticky="w")
        tk.Label(layout, text="Header-Hoehe (cm)").grid(row=0, column=2, padx=6, pady=5, sticky="e")
        tk.Entry(layout, textvariable=self.header_height_cm_var, width=8).grid(row=0, column=3, padx=6, pady=5, sticky="w")
        tk.Label(layout, text="Logo-Breite (cm)").grid(row=0, column=4, padx=6, pady=5, sticky="e")
        tk.Entry(layout, textvariable=self.logo_width_cm_var, width=8).grid(row=0, column=5, padx=6, pady=5, sticky="w")

        form.columnconfigure(1, weight=1)
        form.columnconfigure(2, weight=0)
        form.columnconfigure(3, weight=0)
        form.columnconfigure(4, weight=0)

        middle = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        middle.pack(fill="both", expand=True, padx=8, pady=4)

        left = tk.LabelFrame(middle, text="Zusatzzeilen")
        right = tk.LabelFrame(middle, text="JSON Vorschau")
        middle.add(left, stretch="always")
        middle.add(right, stretch="always")

        tk.Label(left, text="left_lines (eine Zeile pro Zeile)").pack(anchor="w", padx=6, pady=(6, 2))
        self.left_lines_text = scrolledtext.ScrolledText(left, height=12, wrap="word")
        self.left_lines_text.pack(fill="both", expand=True, padx=6, pady=4)

        tk.Label(left, text="right_lines (eine Zeile pro Zeile)").pack(anchor="w", padx=6, pady=(6, 2))
        self.right_lines_text = scrolledtext.ScrolledText(left, height=12, wrap="word")
        self.right_lines_text.pack(fill="both", expand=True, padx=6, pady=4)

        self.output_text = scrolledtext.ScrolledText(right, wrap="none", font=("Consolas", 10))
        self.output_text.pack(fill="both", expand=True, padx=6, pady=6)

        bottom = tk.Frame(self.root)
        bottom.pack(fill="x", padx=8, pady=8)
        tk.Button(bottom, text="Neu", command=self.reset_form).pack(side="left", padx=4)
        tk.Button(bottom, text="Laden", command=self.load_json).pack(side="left", padx=4)
        tk.Button(bottom, text="JSON erzeugen", command=self.build_json_preview).pack(side="left", padx=4)
        tk.Button(bottom, text="Validieren", command=self.validate_current_json).pack(side="left", padx=4)
        tk.Button(bottom, text="Speichern", command=self.save_json).pack(side="left", padx=4)

    def choose_school_info(self) -> None:
        path = filedialog.askopenfilename(
            title="school_info.json auswaehlen",
            initialdir=str(PROJECT_ROOT / "data" / "schools"),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.school_info_ref_var.set(self._to_project_relative(path))

    def choose_logo(self) -> None:
        path = filedialog.askopenfilename(
            title="Logo auswaehlen",
            initialdir=str(PROJECT_ROOT / "data" / "schools"),
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.svg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.logo_path_var.set(self._to_project_relative(path))

    def _to_project_relative(self, abs_path: str) -> str:
        p = Path(abs_path).resolve()
        try:
            rel = p.relative_to(PROJECT_ROOT)
            return str(rel).replace("\\", "/")
        except Exception:
            return str(p).replace("\\", "/")

    def fill_id_from_title(self) -> None:
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("Titel fehlt", "Bitte zuerst einen Titel eingeben.")
            return
        self.id_var.set(slugify_id(title))

    def _lines_from_text(self, widget: scrolledtext.ScrolledText) -> list[str]:
        raw = widget.get("1.0", "end").strip()
        if not raw:
            return []
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def build_json(self) -> dict:
        title = self.title_var.get().strip()
        hid = self.id_var.get().strip()
        if not title:
            raise ValueError("Feld 'Titel' ist pflicht.")
        if not hid:
            raise ValueError("Feld 'ID' ist pflicht.")

        duration_min = parse_int(self.duration_min_var.get(), "Arbeitszeit (min)", 1)
        header_height = parse_float(self.header_height_cm_var.get(), "Header-Hoehe (cm)", 1.0)
        logo_width = parse_float(self.logo_width_cm_var.get(), "Logo-Breite (cm)", 1.0)

        obj: dict = {
            "$schema": "../../schemas/header/header.schema.json",
            "id": hid,
            "title": title,
            "duration_min": duration_min,
            "layout": {
                "show_logo": bool(self.show_logo_var.get()),
                "show_border": bool(self.show_border_var.get()),
                "header_height_cm": header_height,
                "logo_width_cm": logo_width,
            },
            "version": "1.0",
        }

        optional_str_fields = {
            "subtitle": self.subtitle_var.get(),
            "school_name": self.school_name_var.get(),
            "class_name": self.class_name_var.get(),
            "subject": self.subject_var.get(),
            "teacher": self.teacher_var.get(),
            "date": self.date_var.get(),
            "logo_path": self.logo_path_var.get(),
            "school_info_ref": self.school_info_ref_var.get(),
        }
        for key, value in optional_str_fields.items():
            v = value.strip()
            if v:
                obj[key] = v

        left_lines = self._lines_from_text(self.left_lines_text)
        right_lines = self._lines_from_text(self.right_lines_text)
        if left_lines:
            obj["left_lines"] = left_lines
        if right_lines:
            obj["right_lines"] = right_lines

        return obj

    def build_json_preview(self) -> None:
        try:
            self.current_json = self.build_json()
        except Exception as exc:
            messagebox.showerror("Fehler", str(exc))
            return
        rendered = json.dumps(self.current_json, ensure_ascii=False, indent=2)
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", rendered)

    def validate_current_json(self) -> None:
        if self.current_json is None:
            self.build_json_preview()
            if self.current_json is None:
                return
        try:
            validator = make_validator(DEFAULT_SCHEMA)
            errors = sorted(validator.iter_errors(self.current_json), key=lambda e: e.path)
            if errors:
                msg = "\n".join(f"- {list(e.path)}: {e.message}" for e in errors[:20])
                messagebox.showerror("Schema-Fehler", msg)
                return
            messagebox.showinfo("Validierung", "JSON ist gueltig.")
        except Exception as exc:
            messagebox.showerror("Validierung fehlgeschlagen", str(exc))

    def load_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Header JSON laden",
            initialdir=str(DEFAULT_OUT_DIR),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            obj = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Laden fehlgeschlagen", str(exc))
            return

        self.reset_form(clear_preview=False)

        self.id_var.set(str(obj.get("id", "")))
        self.title_var.set(str(obj.get("title", "")))
        self.subtitle_var.set(str(obj.get("subtitle", "")))
        self.school_name_var.set(str(obj.get("school_name", "")))
        self.class_name_var.set(str(obj.get("class_name", "")))
        self.subject_var.set(str(obj.get("subject", "")))
        self.teacher_var.set(str(obj.get("teacher", "")))
        self.date_var.set(str(obj.get("date", "")))
        self.duration_min_var.set(str(obj.get("duration_min", "60")))
        self.logo_path_var.set(str(obj.get("logo_path", "")))
        self.school_info_ref_var.set(str(obj.get("school_info_ref", "")))

        layout = obj.get("layout") or {}
        self.show_logo_var.set(bool(layout.get("show_logo", True)))
        self.show_border_var.set(bool(layout.get("show_border", True)))
        self.header_height_cm_var.set(str(layout.get("header_height_cm", "4.0")))
        self.logo_width_cm_var.set(str(layout.get("logo_width_cm", "3.0")))

        self.left_lines_text.insert("1.0", "\n".join(obj.get("left_lines") or []))
        self.right_lines_text.insert("1.0", "\n".join(obj.get("right_lines") or []))

        self.current_json = obj
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", json.dumps(obj, ensure_ascii=False, indent=2))

    def save_json(self) -> None:
        if self.current_json is None:
            self.build_json_preview()
            if self.current_json is None:
                return
        try:
            validator = make_validator(DEFAULT_SCHEMA)
            errors = sorted(validator.iter_errors(self.current_json), key=lambda e: e.path)
            if errors:
                msg = "\n".join(f"- {list(e.path)}: {e.message}" for e in errors[:20])
                messagebox.showerror("Schema-Fehler", msg)
                return
        except Exception as exc:
            messagebox.showerror("Validierung fehlgeschlagen", str(exc))
            return

        DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
        default_name = f"{self.current_json.get('id', 'header')}.json"
        path = filedialog.asksaveasfilename(
            title="Header JSON speichern",
            initialdir=str(DEFAULT_OUT_DIR),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self.current_json, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            messagebox.showinfo("Gespeichert", f"Datei gespeichert:\n{path}")
        except Exception as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc))

    def reset_form(self, clear_preview: bool = True) -> None:
        self.current_json = None

        self.id_var.set("")
        self.title_var.set("")
        self.subtitle_var.set("")
        self.school_name_var.set("")
        self.class_name_var.set("")
        self.subject_var.set("")
        self.teacher_var.set("")
        self.date_var.set("")
        self.duration_min_var.set("60")
        self.logo_path_var.set("")
        self.school_info_ref_var.set("")

        self.show_logo_var.set(True)
        self.show_border_var.set(True)
        self.header_height_cm_var.set("4.0")
        self.logo_width_cm_var.set("3.0")

        self.left_lines_text.delete("1.0", "end")
        self.right_lines_text.delete("1.0", "end")

        if clear_preview:
            self.output_text.delete("1.0", "end")


def main() -> None:
    root = tk.Tk()
    HeaderGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
