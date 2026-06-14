"""Central secret loader. Env vars win; falls back to gitignored config/secrets.json and .env.

Never hardcode keys in code. Import and call load_secrets() early, or use
get_secret("FINNHUB_API_KEY").
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SECRETS_PATH = _REPO / "config" / "secrets.json"
_DOTENV_PATH = _REPO / ".env"
_loaded = False


def _apply_env_map(data: dict, override: bool = False) -> None:
    for k, v in data.items():
        if k.startswith("_") or v in (None, ""):
            continue
        if override or not os.environ.get(k):
            os.environ[k] = str(v)


def load_dotenv(override: bool = False, path: Path | None = None) -> dict:
    """Populate os.environ from repo .env (KEY=VALUE lines) without clobbering real env vars."""
    env_path = path or _DOTENV_PATH
    applied: dict = {}
    if not env_path.exists():
        return applied
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip()
            if val and val[0] in ("'", '"') and val[-1] == val[0]:
                val = val[1:-1]
            if override or not os.environ.get(key):
                os.environ[key] = val
                applied[key] = val
    except OSError as exc:
        print(f"[secrets] could not read {env_path}: {exc}", flush=True)
    return applied


def load_secrets(override: bool = False) -> dict:
    """Populate os.environ from .env and config/secrets.json without clobbering real env vars."""
    global _loaded
    dotenv_data = load_dotenv(override=override)
    data: dict = {}
    if _SECRETS_PATH.exists():
        try:
            data = json.loads(_SECRETS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[secrets] could not read {_SECRETS_PATH}: {exc}", flush=True)
            data = {}
    _apply_env_map(data, override=override)
    _loaded = True
    return {**dotenv_data, **{k: v for k, v in data.items() if not str(k).startswith("_")}}


def get_secret(name: str, default: str | None = None) -> str | None:
    if not _loaded:
        load_secrets()
    val = os.environ.get(name)
    return val if val not in (None, "") else default
