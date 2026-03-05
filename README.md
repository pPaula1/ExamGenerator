# ExamGenerator

## Data Layout

Nutzdaten liegen unter `data/`:

- `data/schools/`
- `data/headers/` (geplant)
- `data/exams/`
- `tasks/` (bestehende Aufgaben-JSONs)

## Generator Scripts

Generatoren liegen jetzt unter:

- `tools/generators/task_json_builder_gui.py`
- `tools/renderers/task_pdf_renderer.py`
- `tools/renderers/workspace_renderer.py`
- `tools/generators/header_generator.py`

### PDF aus JSON erzeugen

Neuer Pfad:

```powershell
python .\tools\generators\task_pdf_renderer.py --input .\tasks --output-dir .\out_pdf --name exam_test --title "Aufgaben"
```

Kompatibel bleibt auch:

```powershell
python .\json_to_pdf.py --input .\tasks --output-dir .\out_pdf --name exam_test --title "Aufgaben"
```

### Header JSON per GUI erzeugen

```powershell
python .\tools\generators\header_generator.py
```

## Neue Schemas

- `schemas/exam/exam.schema.json`
- `schemas/header/header.schema.json`
- `schemas/school/school_info.schema.json`

