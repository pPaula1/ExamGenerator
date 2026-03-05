#!/usr/bin/env python3
"""
JSON_Generator.py

Simple manual GUI for creating task JSON.
- Beginner mode: only essential fields
- Expert mode: optional metadata
- Schema validation
- Save JSON
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from jsonschema import Draft202012Validator, RefResolver


ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = ROOT / "schemas" / "task" / "task.schema.json"
ALLOWED_IMAGE_EXTS = {".svg", ".png", ".jpg", ".jpeg", ".webp"}


def slugify_id(text: str) -> str:
    s = text.lower().strip()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if len(s) < 3:
        s = (s + "_task")[:6]
    return s[:65]


def parse_non_negative_number(value: str, field_name: str) -> float | int:
    v = value.strip().replace(",", ".")
    if not v:
        raise ValueError(f"Feld '{field_name}' darf nicht leer sein.")
    n = float(v)
    if n < 0:
        raise ValueError(f"Feld '{field_name}' muss >= 0 sein.")
    return int(n) if n.is_integer() else n


def make_validator(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    resolver = RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema)
    return Draft202012Validator(schema, resolver=resolver)


class JsonGeneratorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("JSON Generator (einfach)")
        self.root.geometry("1200x820")

        self.parts: list[dict] = []
        self.assets: list[dict] = []
        self.current_json: dict | None = None

        self.schema_var = tk.StringVar(value=str(DEFAULT_SCHEMA))
        self.expert_mode = tk.BooleanVar(value=False)

        self.task_id_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.points_var = tk.StringVar(value="5")
        self.subject_var = tk.StringVar()
        self.topic_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self.version_var = tk.StringVar(value="1.0")
        self.source_ref_var = tk.StringVar()
        self.source_notes_var = tk.StringVar()

        self.part_id_var = tk.StringVar(value="a")
        self.part_points_var = tk.StringVar(value="1")
        self.asset_path_var = tk.StringVar()
        self.asset_caption_var = tk.StringVar()
        self.asset_width_var = tk.StringVar(value="0.8\\linewidth")
        self.asset_placement_var = tk.StringVar(value="below_statement")
        self.asset_column_var = tk.StringVar(value="full")

        self._build_ui()

    def _build_ui(self) -> None:
        top = tk.LabelFrame(self.root, text="Grunddaten")
        top.pack(fill="x", padx=8, pady=8)

        tk.Label(top, text="Schema").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        tk.Entry(top, textvariable=self.schema_var, width=90).grid(row=0, column=1, columnspan=4, sticky="we", padx=6, pady=6)

        tk.Label(top, text="Titel*").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        tk.Entry(top, textvariable=self.name_var, width=50).grid(row=1, column=1, sticky="we", padx=6, pady=6)
        tk.Button(top, text="ID aus Titel", command=self.fill_id_from_title).grid(row=1, column=2, padx=6, pady=6)
        tk.Label(top, text="ID*").grid(row=1, column=3, sticky="e", padx=6, pady=6)
        tk.Entry(top, textvariable=self.task_id_var, width=24).grid(row=1, column=4, sticky="w", padx=6, pady=6)

        tk.Label(top, text="Punkte*").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        tk.Entry(top, textvariable=self.points_var, width=10).grid(row=2, column=1, sticky="w", padx=6, pady=6)
        tk.Label(top, text="Aufgabentext*").grid(row=3, column=0, sticky="nw", padx=6, pady=6)
        self.statement_text = scrolledtext.ScrolledText(top, height=5, wrap="word")
        self.statement_text.grid(row=3, column=1, columnspan=4, sticky="we", padx=6, pady=6)

        top.columnconfigure(1, weight=1)

        mid = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        left = tk.Frame(mid)
        right = tk.Frame(mid)
        mid.add(left, stretch="always")
        mid.add(right, stretch="always")

        self._build_parts_ui(left)
        self._build_assets_ui(left)
        self._build_expert_ui(right)
        self._build_output_ui(right)

        bottom = tk.Frame(self.root)
        bottom.pack(fill="x", padx=8, pady=8)
        tk.Button(bottom, text="Neues Formular", command=self.reset_form).pack(side="left", padx=4)
        tk.Button(bottom, text="JSON erzeugen", command=self.build_json_preview).pack(side="left", padx=4)
        tk.Button(bottom, text="Validieren", command=self.validate_current_json).pack(side="left", padx=4)
        tk.Button(bottom, text="Speichern", command=self.save_json).pack(side="left", padx=4)

    def _build_parts_ui(self, parent: tk.Widget) -> None:
        frame = tk.LabelFrame(parent, text="Teilaufgaben (optional)")
        frame.pack(fill="both", expand=True, pady=4)

        self.parts_list = tk.Listbox(frame, height=8)
        self.parts_list.pack(fill="x", padx=6, pady=6)

        row = tk.Frame(frame)
        row.pack(fill="x", padx=6, pady=4)
        tk.Label(row, text="ID").pack(side="left")
        tk.Entry(row, textvariable=self.part_id_var, width=5).pack(side="left", padx=4)
        tk.Label(row, text="Punkte").pack(side="left")
        tk.Entry(row, textvariable=self.part_points_var, width=7).pack(side="left", padx=4)

        tk.Label(frame, text="Text").pack(anchor="w", padx=6)
        self.part_text = scrolledtext.ScrolledText(frame, height=3, wrap="word")
        self.part_text.pack(fill="x", padx=6, pady=4)

        btns = tk.Frame(frame)
        btns.pack(fill="x", padx=6, pady=4)
        tk.Button(btns, text="Teilaufgabe hinzufügen", command=self.add_part).pack(side="left", padx=3)
        tk.Button(btns, text="Auswahl entfernen", command=self.remove_part).pack(side="left", padx=3)

    def _build_assets_ui(self, parent: tk.Widget) -> None:
        frame = tk.LabelFrame(parent, text="Bilder (optional)")
        frame.pack(fill="both", expand=True, pady=4)

        self.assets_list = tk.Listbox(frame, height=8)
        self.assets_list.pack(fill="x", padx=6, pady=6)

        row1 = tk.Frame(frame)
        row1.pack(fill="x", padx=6, pady=2)
        tk.Label(row1, text="Bild-Pfad").pack(side="left")
        tk.Entry(row1, textvariable=self.asset_path_var, width=42).pack(side="left", padx=4, fill="x", expand=True)
        tk.Button(row1, text="Datei wählen", command=self.choose_image).pack(side="left", padx=4)

        row2 = tk.Frame(frame)
        row2.pack(fill="x", padx=6, pady=2)
        tk.Label(row2, text="Platzierung").pack(side="left")
        ttk.Combobox(
            row2,
            textvariable=self.asset_placement_var,
            values=["below_statement", "right_of_statement", "below_part_text", "inline"],
            width=18,
            state="readonly",
        ).pack(side="left", padx=4)
        tk.Label(row2, text="Spalte").pack(side="left")
        ttk.Combobox(
            row2,
            textvariable=self.asset_column_var,
            values=["full", "left", "right"],
            width=8,
            state="readonly",
        ).pack(side="left", padx=4)
        tk.Label(row2, text="Breite").pack(side="left")
        tk.Entry(row2, textvariable=self.asset_width_var, width=16).pack(side="left", padx=4)

        row3 = tk.Frame(frame)
        row3.pack(fill="x", padx=6, pady=2)
        tk.Label(row3, text="Bildunterschrift").pack(side="left")
        tk.Entry(row3, textvariable=self.asset_caption_var, width=45).pack(side="left", padx=4, fill="x", expand=True)

        btns = tk.Frame(frame)
        btns.pack(fill="x", padx=6, pady=4)
        tk.Button(btns, text="Bild hinzufügen", command=self.add_asset).pack(side="left", padx=3)
        tk.Button(btns, text="Auswahl entfernen", command=self.remove_asset).pack(side="left", padx=3)

    def _build_expert_ui(self, parent: tk.Widget) -> None:
        container = tk.LabelFrame(parent, text="Optionen")
        container.pack(fill="x", pady=4)

        tk.Checkbutton(
            container,
            text="Expertenmodus anzeigen",
            variable=self.expert_mode,
            command=self.toggle_expert_mode,
        ).pack(anchor="w", padx=6, pady=6)

        self.expert_frame = tk.Frame(container)
        self.expert_frame.pack(fill="x", padx=6, pady=6)

        tk.Label(self.expert_frame, text="Fach").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        tk.Entry(self.expert_frame, textvariable=self.subject_var, width=20).grid(row=0, column=1, sticky="w", padx=4, pady=3)
        tk.Label(self.expert_frame, text="Thema").grid(row=0, column=2, sticky="w", padx=4, pady=3)
        tk.Entry(self.expert_frame, textvariable=self.topic_var, width=20).grid(row=0, column=3, sticky="w", padx=4, pady=3)
        tk.Label(self.expert_frame, text="Tags (Komma getrennt)").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        tk.Entry(self.expert_frame, textvariable=self.tags_var, width=55).grid(row=1, column=1, columnspan=3, sticky="we", padx=4, pady=3)
        tk.Label(self.expert_frame, text="Version").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        tk.Entry(self.expert_frame, textvariable=self.version_var, width=10).grid(row=2, column=1, sticky="w", padx=4, pady=3)
        tk.Label(self.expert_frame, text="Quelle").grid(row=3, column=0, sticky="w", padx=4, pady=3)
        tk.Entry(self.expert_frame, textvariable=self.source_ref_var, width=55).grid(row=3, column=1, columnspan=3, sticky="we", padx=4, pady=3)
        tk.Label(self.expert_frame, text="Quell-Notiz").grid(row=4, column=0, sticky="w", padx=4, pady=3)
        tk.Entry(self.expert_frame, textvariable=self.source_notes_var, width=55).grid(row=4, column=1, columnspan=3, sticky="we", padx=4, pady=3)

        self.toggle_expert_mode()

    def _build_output_ui(self, parent: tk.Widget) -> None:
        frame = tk.LabelFrame(parent, text="JSON-Vorschau")
        frame.pack(fill="both", expand=True, pady=4)
        self.output_text = scrolledtext.ScrolledText(frame, wrap="none", font=("Consolas", 10))
        self.output_text.pack(fill="both", expand=True, padx=6, pady=6)

    def toggle_expert_mode(self) -> None:
        if self.expert_mode.get():
            self.expert_frame.pack(fill="x", padx=6, pady=6)
        else:
            self.expert_frame.pack_forget()

    def fill_id_from_title(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Titel fehlt", "Bitte zuerst einen Titel eingeben.")
            return
        self.task_id_var.set(slugify_id(name))

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Bild auswählen",
            filetypes=[
                ("Image files", "*.svg *.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.asset_path_var.set(path.replace("\\", "/"))

    def add_part(self) -> None:
        part_id = self.part_id_var.get().strip()
        part_text = self.part_text.get("1.0", "end").strip()
        points_raw = self.part_points_var.get().strip()
        if not part_id or not part_text:
            messagebox.showwarning("Fehlende Daten", "Teilaufgabe braucht mindestens ID und Text.")
            return
        try:
            part: dict = {"id": part_id, "text": part_text}
            if points_raw:
                part["points"] = parse_non_negative_number(points_raw, "Teilaufgabe Punkte")
        except Exception as exc:
            messagebox.showerror("Ungültige Eingabe", str(exc))
            return

        self.parts.append(part)
        self.parts_list.insert("end", f"{part['id']}: {part['text'][:55]}")
        self.part_text.delete("1.0", "end")

    def remove_part(self) -> None:
        sel = self.parts_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.parts_list.delete(idx)
        self.parts.pop(idx)

    def add_asset(self) -> None:
        path = self.asset_path_var.get().strip()
        if not path:
            messagebox.showwarning("Fehlende Daten", "Bitte Bild-Pfad eingeben.")
            return
        ext = Path(path).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTS:
            messagebox.showwarning("Ungültiger Pfad", "Erlaubte Formate: svg, png, jpg, jpeg, webp.")
            return

        asset = {
            "path": path,
            "placement": self.asset_placement_var.get().strip() or "below_statement",
            "column": self.asset_column_var.get().strip() or "full",
            "width": self.asset_width_var.get().strip() or "0.8\\linewidth",
        }
        caption = self.asset_caption_var.get().strip()
        if caption:
            asset["caption"] = caption

        self.assets.append(asset)
        self.assets_list.insert("end", f"{asset['column']} | {Path(path).name}")
        self.asset_path_var.set("")
        self.asset_caption_var.set("")

    def remove_asset(self) -> None:
        sel = self.assets_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.assets_list.delete(idx)
        self.assets.pop(idx)

    def _build_json(self) -> dict:
        task_id = self.task_id_var.get().strip()
        name = self.name_var.get().strip()
        statement = self.statement_text.get("1.0", "end").strip()

        if not task_id or not name or not statement:
            raise ValueError("Bitte die Pflichtfelder ID, Titel und Aufgabentext ausfüllen.")

        task = {
            "id": task_id,
            "name": name,
            "statement": statement,
            "points": parse_non_negative_number(self.points_var.get(), "Punkte"),
        }

        if self.parts:
            task["parts"] = self.parts
        if self.assets:
            task["assets"] = self.assets

        if self.expert_mode.get():
            subject = self.subject_var.get().strip()
            topic = self.topic_var.get().strip()
            tags = [t.strip() for t in self.tags_var.get().split(",") if t.strip()]
            version = self.version_var.get().strip()
            src_ref = self.source_ref_var.get().strip()
            src_notes = self.source_notes_var.get().strip()

            if subject:
                task["subject"] = subject
            if topic:
                task["topic"] = topic
            if tags:
                task["tags"] = tags
            if version:
                task["version"] = version
            if src_ref or src_notes:
                source = {}
                if src_ref:
                    source["ref"] = src_ref
                if src_notes:
                    source["notes"] = src_notes
                task["source"] = source

        return task

    def build_json_preview(self) -> None:
        try:
            self.current_json = self._build_json()
            pretty = json.dumps(self.current_json, ensure_ascii=False, indent=2)
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", pretty)
        except Exception as exc:
            messagebox.showerror("JSON konnte nicht erzeugt werden", str(exc))

    def validate_current_json(self) -> None:
        raw = self.output_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("Keine JSON-Vorschau", "Bitte zuerst 'JSON erzeugen' klicken.")
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            messagebox.showerror("Ungültiges JSON", str(exc))
            return

        schema_path = Path(self.schema_var.get().strip())
        if not schema_path.exists():
            messagebox.showerror("Schema fehlt", f"Schema-Datei nicht gefunden: {schema_path}")
            return

        try:
            validator = make_validator(schema_path)
            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            if not errors:
                messagebox.showinfo("Validierung", "JSON ist gültig.")
                return

            lines = []
            for err in errors:
                path = ".".join(str(x) for x in err.path) if err.path else "<root>"
                lines.append(f"- {path}: {err.message}")
            messagebox.showwarning("Validierung fehlgeschlagen", "\n".join(lines[:10]))
        except Exception as exc:
            messagebox.showerror("Validierung fehlgeschlagen", str(exc))

    def save_json(self) -> None:
        raw = self.output_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("Keine JSON-Vorschau", "Bitte zuerst 'JSON erzeugen' klicken.")
            return
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            messagebox.showerror("Ungültiges JSON", str(exc))
            return

        initial = f"{parsed.get('id', 'task')}.json"
        path = filedialog.asksaveasfilename(
            title="Aufgabe als JSON speichern",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile=initial,
        )
        if not path:
            return
        Path(path).write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo("Gespeichert", f"Datei gespeichert:\n{path}")

    def reset_form(self) -> None:
        self.task_id_var.set("")
        self.name_var.set("")
        self.points_var.set("5")
        self.statement_text.delete("1.0", "end")
        self.parts.clear()
        self.assets.clear()
        self.parts_list.delete(0, "end")
        self.assets_list.delete(0, "end")
        self.part_id_var.set("a")
        self.part_points_var.set("1")
        self.part_text.delete("1.0", "end")
        self.asset_path_var.set("")
        self.asset_caption_var.set("")
        self.asset_width_var.set("0.8\\linewidth")
        self.asset_placement_var.set("below_statement")
        self.asset_column_var.set("full")
        self.subject_var.set("")
        self.topic_var.set("")
        self.tags_var.set("")
        self.version_var.set("1.0")
        self.source_ref_var.set("")
        self.source_notes_var.set("")
        self.output_text.delete("1.0", "end")
        self.current_json = None


def main() -> None:
    root = tk.Tk()
    app = JsonGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
