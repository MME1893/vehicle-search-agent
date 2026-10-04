import csv
import json
from pathlib import Path


def rows(path: str, collection_key: str | None = None) -> list[dict]:
    """Load import rows from a JSON array/object or a CSV file."""
    source = Path(path)
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            raise ValueError("Expected a top-level JSON array or object")

        key = collection_key or "items"
        if key not in payload or not isinstance(payload[key], list):
            raise ValueError(f"Expected top-level JSON array '{key}'")
        return payload[key]
    with source.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def list_value(value):
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [item.strip() for item in value.split("|") if item.strip()]
        if isinstance(parsed, list):
            return parsed
    raise ValueError("oem_approvals must be a list")
