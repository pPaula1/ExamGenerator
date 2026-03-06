# ExamGenerator

Erzeugt PrÃ¼fungs-PDFs aus JSON-Daten (Schule, Header, Aufgaben).

## Struktur

- `schemas/`  
  JSON-Schemas fÃ¼r `task`, `header`, `exam`, `school`.
- `data/schools/`  
  Schulinfos + Logos.
- `data/headers/`  
  Header-JSONs.
- `data/tasks/`  
  Aufgaben-JSONs + Assets.
- `data/exams/`  
  Exam-JSONs (referenzieren Header + Tasks + School).
- `tools/renderers/`  
  PrimÃ¤re Renderer.

## Standardbefehle

### 1) Header rendern

```powershell
python .\tools\renderers\header_pdf_renderer.py --input .\data\headers\header_example_math_2_schulaufgabe.json --output-dir .\out_pdf --name header_test
```

### 2) Tasks rendern

```powershell
python .\tools\renderers\task_pdf_renderer.py --input .\data\tasks --output-dir .\out_pdf --name tasks_test --title "Aufgaben"
```

### 3) Komplettes Exam rendern

```powershell
python .\tools\renderers\exam_pdf_renderer.py --input .\data\exams\exam_all_tasks_example.json --output-dir .\out_pdf --name exam_test
```

## Wichtige Render-Logik

- `exam` lÃ¤dt Header + School + Tasks und berechnet Gesamtpunkte.
- SeitenumbrÃ¼che zwischen Tasks sind weich (`Needspace`) statt hart.
- Standardregel: neue Task nur auf neue Seite, wenn < 30% Restplatz frei ist.
- Workspaces sind auch bei Unteraufgaben korrekt zentriert.

## Schema-Validierung

Vor dem Rendern wird validiert gegen:

- `exam.schema.json`
- `header.schema.json`
- `task.schema.json`
- `school_info.schema.json` (wenn referenziert)

Bei Fehlern bricht der Renderer mit konkreter Meldung ab.

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Abgedeckt sind u. a.:

- Ref-AuflÃ¶sung auf `data/tasks`
- Workspace-Zentrierung (normal vs. Unteraufgabe)
- Schema-Validierung fÃ¼r Exam/Task
- Soft-Pagebreak-Flag zwischen Aufgaben

## Troubleshooting

- `pdflatex not found`  
  MiKTeX/TeX Live installieren und `pdflatex` in `PATH` verfÃ¼gbar machen.
- `Error validating ... schema`  
  JSON gegen die Pfade/Feldnamen im jeweiligen Schema prÃ¼fen.
- Bilder fehlen im PDF  
  `assets.path` ist relativ zur Task-JSON (mit Fallback auf den Ã¼bergeordneten Ordner).

