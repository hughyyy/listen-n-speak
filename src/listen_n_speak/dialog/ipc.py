"""Result-file IPC between the server and the dialog subprocess."""

from __future__ import annotations

import json
from pathlib import Path


def write_result(path: Path, payload: dict) -> None:
    """Atomically write the dialog result as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_result(path: Path) -> dict | None:
    """Read a dialog result; None when absent or malformed."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
