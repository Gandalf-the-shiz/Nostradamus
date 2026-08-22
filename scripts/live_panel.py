"""Live ML panel collector — liquid-first, fail-closed.

Shared by generate_live_predictions.py (panel write) and fetch-history.py
(ticker collector) so the 2500-name cap is applied AFTER the tradeable
universe filter, not before it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HIST_DIR = REPO / "data" / "historical"
DEFAULT_PANEL_LIMIT = int(os.getenv("LIVE_PREDICT_LIMIT", "2500"))

SKIP_HIST_META = frozenset({
    "manifest.json",
    "multiyear-coverage.json",
    "stooq-bulk-coverage.json",
    "_live.json",
})

SECTOR_BY_FILENAME = {
    "technology": "Technology",
    "healthcare": "Healthcare",
    "financials": "Financials",
    "consumer_discretionary": "Consumer Discretionary",
    "consumer_staples": "Consumer Staples",
    "energy": "Energy",
    "industrials": "Industrials",
    "materials": "Materials",
    "real_estate": "Real Estate",
    "utilities": "Utilities",
    "communication_services": "Communication Services",
    "other": "Other",
}

sys.path.insert(0, str(REPO / "scripts"))


def collect_panel_entries(limit: int = DEFAULT_PANEL_LIMIT, *, include_candles: bool = False) -> list[dict]:
    """Yield tradeable symbols in shard order until ``limit`` is filled.

    Non-tradeable names (warrants, units, illiquid, missing ADV) are dropped
    *before* the cap so the live panel is liquid-first, not newest-garbage-first.
    """
    from intelligence.tradeable_universe import is_tradeable

    entries: list[dict] = []
    if not HIST_DIR.exists():
        return entries
    dropped = 0
    for fp in sorted(HIST_DIR.glob("*.json")):
        if fp.name in SKIP_HIST_META or fp.name.startswith("manifest"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sector = data.get("sector") or SECTOR_BY_FILENAME.get(fp.stem, "Other")
        for sym, payload in (data.get("stocks") or {}).items():
            info = payload if isinstance(payload, dict) else {}
            ok, reason = is_tradeable(str(sym or ""))
            if not ok:
                dropped += 1
                continue
            entry = {
                "symbol": str(sym).upper(),
                "sector": sector,
                "name": info.get("name", ""),
                "exchange": info.get("exchange", ""),
                "reason": reason,
            }
            if include_candles:
                entry["candles"] = info.get("candles") or []
            entries.append(entry)
            if limit and len(entries) >= limit:
                print(
                    f"[live-panel] collected {len(entries)} tradeable (dropped {dropped} before cap)",
                    flush=True,
                )
                return entries
    print(
        f"[live-panel] collected {len(entries)} tradeable (dropped {dropped} before cap)",
        flush=True,
    )
    return entries


def collect_panel_tickers(limit: int = DEFAULT_PANEL_LIMIT) -> list[dict]:
    """Ticker-collector shape (no candles) — used by fetch-history.py."""
    return collect_panel_entries(limit=limit, include_candles=False)


if __name__ == "__main__":
    rows = collect_panel_entries()
    print(json.dumps({"n": len(rows), "head": [r["symbol"] for r in rows[:12]]}, indent=2))
