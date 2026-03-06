#!/usr/bin/env python3
"""
Shared JSON schema validation utilities for renderers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver
from jsonschema.exceptions import RefResolutionError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _schema_path(kind: str) -> Path:
    mapping = {
        "task": PROJECT_ROOT / "schemas" / "task" / "task.schema.json",
        "header": PROJECT_ROOT / "schemas" / "header" / "header.schema.json",
        "exam": PROJECT_ROOT / "schemas" / "exam" / "exam.schema.json",
        "school": PROJECT_ROOT / "schemas" / "school" / "school_info.schema.json",
    }
    if kind not in mapping:
        raise ValueError(f"Unknown schema kind: {kind}")
    return mapping[kind]


def _strip_ids(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k == "$id":
                continue
            out[k] = _strip_ids(v)
        return out
    if isinstance(value, list):
        return [_strip_ids(v) for v in value]
    return value


def validate_instance(instance: dict[str, Any], kind: str, label: str = "JSON") -> None:
    schema_path = _schema_path(kind)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # Local project validation should resolve refs by file path, not custom schema IDs.
    schema = _strip_ids(schema)
    resolver = RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema)
    validator = Draft202012Validator(schema, resolver=resolver)
    try:
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    except RefResolutionError:
        if kind == "task":
            _validate_task_minimal(instance, label)
            return
        raise
    if not errors:
        return
    preview = []
    for e in errors[:12]:
        path = ".".join(str(p) for p in e.absolute_path) or "$"
        preview.append(f"- {path}: {e.message}")
    raise ValueError(f"{label} is not valid against '{kind}' schema:\n" + "\n".join(preview))


def _validate_task_minimal(instance: dict[str, Any], label: str) -> None:
    required_top = ("id", "name", "statement", "points")
    for key in required_top:
        if key not in instance:
            raise ValueError(f"{label} is not valid task JSON: missing '{key}'")
    if not isinstance(instance.get("id"), str) or not instance["id"].strip():
        raise ValueError(f"{label} is not valid task JSON: 'id' must be non-empty string")
    if not isinstance(instance.get("name"), str) or not instance["name"].strip():
        raise ValueError(f"{label} is not valid task JSON: 'name' must be non-empty string")
    if not isinstance(instance.get("statement"), str) or not instance["statement"].strip():
        raise ValueError(f"{label} is not valid task JSON: 'statement' must be non-empty string")
    try:
        float(instance.get("points"))
    except Exception as exc:
        raise ValueError(f"{label} is not valid task JSON: 'points' must be numeric") from exc

    for i, part in enumerate(instance.get("parts") or []):
        if not isinstance(part, dict):
            raise ValueError(f"{label} is not valid task JSON: parts[{i}] must be object")
        if not str(part.get("id", "")).strip():
            raise ValueError(f"{label} is not valid task JSON: parts[{i}].id missing")
        has_text = bool(str(part.get("text", "")).strip())
        checkbox_items = part.get("checkbox_items")
        has_checkbox_items = isinstance(checkbox_items, list) and len(checkbox_items) > 0
        matching = part.get("matching")
        has_matching = (
            isinstance(matching, dict)
            and isinstance(matching.get("left_items"), list)
            and len(matching.get("left_items")) > 0
            and isinstance(matching.get("right_items"), list)
            and len(matching.get("right_items")) > 0
        )
        table = part.get("table")
        has_table = (
            isinstance(table, dict)
            and isinstance(table.get("headers"), list)
            and len(table.get("headers")) > 0
            and isinstance(table.get("rows"), list)
            and len(table.get("rows")) > 0
        )
        textboxes = part.get("textboxes")
        has_textboxes = isinstance(textboxes, list) and len(textboxes) > 0
        if not has_text and not has_checkbox_items and not has_matching and not has_table and not has_textboxes:
            raise ValueError(
                f"{label} is not valid task JSON: parts[{i}] requires either non-empty 'text', 'checkbox_items', 'matching', 'table' or 'textboxes'"
            )
