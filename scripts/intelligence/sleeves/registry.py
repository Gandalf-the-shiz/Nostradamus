"""Sleeve registry — the crew that actually gets capital weight.

Writes data/intelligence/sleeves/registry.json from sleeve_ic.json,
the edge ledger, and config/alpha_engine.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT_PATH = REPO / "data" / "intelligence" / "sleeves" / "registry.json"
SLEEVE_IC = REPO / "data" / "accuracy" / "sleeve_ic.json"
CONFIG_PATH = REPO / "config" / "alpha_engine.json"

FAMILIES = {
    "ml_edge": "ml",
    "ml_proba": "ml",
    "reversal_1d": "price",
    "reversal_5d": "price",
    "momentum_120_20": "price",
    "pead": "fundamental",
    "revisions": "fundamental",
    "sentiment": "sentiment",
}

HORIZONS = {
    "reversal_1d": "1d",
    "reversal_5d": "5d",
    "momentum_120_20": "120d",
    "pead": "event",
    "revisions": "event",
    "sentiment": "1d",
    "ml_edge": "1d",
    "ml_proba": "1d",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _status(name: str, *, weight: float, n_days: int, killed: bool, decayed: bool, min_days: int) -> str:
    if killed:
        return "killed"
    if weight > 0 and n_days >= min_days:
        return "live"
    if decayed:
        return "watch"
    return "shadow"


def write_registry(sleeve_ic: dict | None = None) -> dict:
    ic = sleeve_ic if sleeve_ic is not None else _load(SLEEVE_IC)
    cfg = _load(CONFIG_PATH)
    config_w = dict(cfg.get("sleeve_weights") or ic.get("config_weights") or {})
    effective = dict(ic.get("effective_weights") or {})
    forward = ic.get("forward") or {}
    by_sleeve = forward.get("by_sleeve") or {}
    research = (ic.get("research") or {}).get("by_sleeve") or {}
    min_days = max(int(ic.get("min_forward_days") or 20), 20)
    pairwise = ic.get("pairwiseRho") or {}
    rho_skipped = bool(ic.get("rhoSkipped"))

    try:
        from intelligence.edge_ledger import killed_ids, verdicts
        killed = killed_ids("sleeve")
        verd = verdicts()
    except Exception:
        killed, verd = set(), {}

    names = sorted(set(list(config_w) + list(effective) + list(by_sleeve) + list(research)))
    sleeves = []
    for name in names:
        stats = by_sleeve.get(name) or {}
        res = research.get(name) or {}
        n_days = int(stats.get("n_days") or 0)
        is_killed = name in killed or verd.get(f"sleeve:{name}") == "kill"
        w = float(effective.get(name, 0.0) or 0.0)
        # Shadow / killed sleeves do not run the book — do not echo stale config weights.
        if is_killed or n_days < min_days:
            w = 0.0
        sleeves.append({
            "id": name,
            "family": FAMILIES.get(name, "other"),
            "horizon": HORIZONS.get(name, "1d"),
            "status": _status(name, weight=w, n_days=n_days, killed=is_killed,
                              decayed=bool(stats.get("decayed")), min_days=min_days),
            "forwardIC": stats.get("mean_ic"),
            "icir": stats.get("icir"),
            "nDays": n_days,
            "pairwiseRho": pairwise.get(name) or None,
            "netSpread": stats.get("net_spread") or res.get("net_spread"),
            "weight": w,
            "label": stats.get("label") or res.get("label") or name,
        })

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "source": "sleeve_ic+edge_ledger+alpha_engine",
        "minForwardDays": min_days,
        "weightMode": ic.get("weight_mode"),
        "rhoSkipped": rho_skipped,
        "nSleeves": len(sleeves),
        "sleeves": sleeves,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[sleeves] registry {len(sleeves)} entries → {OUT_PATH}", flush=True)
    return doc


if __name__ == "__main__":
    print(json.dumps(write_registry(), indent=2))
