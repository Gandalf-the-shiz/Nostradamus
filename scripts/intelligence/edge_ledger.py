"""Edge ledger — human / factory kill list for sleeves and fleet agents.

Reads data/intelligence/edge/ledger.json. Accepts a few shapes so a thin
file written by hand still works. Never invents verdicts.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO / "data" / "intelligence" / "edge" / "ledger.json"


def load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return {}
    try:
        doc = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _norm_verdict(val) -> str:
    v = str(val or "").strip().lower()
    if v in {"kill", "killed", "retire", "retired", "dead"}:
        return "kill"
    if v in {"watch", "shadow"}:
        return "watch"
    if v in {"keep", "live", "ok"}:
        return "keep"
    return v


def verdicts() -> dict[str, str]:
    """Map ``fleet:<id>`` / ``sleeve:<id>`` → verdict."""
    doc = load_ledger()
    out: dict[str, str] = {}
    entries = doc.get("entries")
    if isinstance(entries, list):
        for row in entries:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or "").strip()
            if not eid:
                continue
            out[eid] = _norm_verdict(row.get("verdict") or row.get("status"))
    kills = doc.get("kills")
    if isinstance(kills, list):
        for eid in kills:
            if eid:
                out[str(eid)] = "kill"
    for key, val in doc.items():
        if key in {"entries", "kills", "generatedAt", "notes", "ok"}:
            continue
        if isinstance(val, dict) and (val.get("verdict") or val.get("status")):
            out[str(key)] = _norm_verdict(val.get("verdict") or val.get("status"))
        elif isinstance(val, str) and ":" in str(key):
            out[str(key)] = _norm_verdict(val)
    return {k: v for k, v in out.items() if v}


def killed_ids(prefix: str) -> set[str]:
    """Ids under a prefix (``fleet`` / ``sleeve``) whose verdict is kill."""
    pref = f"{prefix.rstrip(':')}:"
    out: set[str] = set()
    for key, verd in verdicts().items():
        if verd != "kill":
            continue
        if key.startswith(pref):
            out.add(key[len(pref):])
        elif key == prefix:
            out.add(key)
    return out
