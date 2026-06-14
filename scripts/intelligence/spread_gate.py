"""Shared fleet promotion spread gate — holdout mean_quintile_spread must be > 0."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERDICTS_PATH = REPO / "data" / "intelligence" / "research" / "verdicts.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_spread_verdict(
    survivor: dict,
    *,
    reasons: list[str],
    holdout: dict,
    promotion_type: str,
    hypothesis_id: str,
) -> None:
    VERDICTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": _now(),
        "hypothesisId": hypothesis_id,
        "type": promotion_type,
        "statement": f"Survivor {survivor.get('id')} fleet promotion spread gate",
        "verdict": "reject",
        "reasons": reasons,
        "evidence": {
            "survivorId": survivor.get("id"),
            "signal": survivor.get("signal", "edge"),
            "holdoutSharpe": (survivor.get("holdout") or {}).get("sharpe"),
            "holdout": holdout,
        },
        "experimentEngine": "walkforward_engine",
    }
    with VERDICTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def spread_gate_filter(
    survivors: list[dict],
    *,
    selection_frac: float,
    promotion_type: str,
    hypothesis_id_fn: Callable[[dict], str],
) -> tuple[list[dict], list[dict]]:
    """Confirm holdout tradeable spread via walkforward_engine before fleet promotion."""
    from intelligence.walkforward_engine import promotion_verdict, run as wf_run

    signal_cache: dict[str, dict] = {}
    passed: list[dict] = []
    rejected: list[dict] = []

    for s in survivors:
        signal = s.get("signal") or "edge"
        if signal not in signal_cache:
            wf = wf_run(signal=signal, selection_frac=selection_frac, rebuild_panel=False)
            if not wf.get("ok"):
                signal_cache[signal] = {
                    "verdict": "reject",
                    "reasons": [wf.get("message") or "walkforward_failed"],
                    "holdout": {},
                }
            else:
                holdout = wf.get("holdout") or {}
                label, reasons = promotion_verdict(holdout, min_spread=0.0)
                signal_cache[signal] = {"verdict": label, "reasons": reasons, "holdout": holdout}

        sr = signal_cache[signal]
        holdout = sr["holdout"]
        reasons = list(sr["reasons"])
        hold_sharpe = (s.get("holdout") or {}).get("sharpe")
        spread = holdout.get("mean_quintile_spread")

        if sr["verdict"] == "reject":
            reject = True
        elif hold_sharpe and hold_sharpe > 0.5 and (spread is None or spread <= 0):
            reasons = reasons + ["sharpe_proxy_high_but_spread_negative"]
            reject = True
        else:
            reject = False

        if reject:
            rejected.append({**s, "spreadGateReasons": reasons})
            _append_spread_verdict(
                s,
                reasons=reasons,
                holdout=holdout,
                promotion_type=promotion_type,
                hypothesis_id=hypothesis_id_fn(s),
            )
        else:
            passed.append(s)

    return passed, rejected
