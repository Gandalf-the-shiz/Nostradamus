"""Day-by-day walk-forward engine with locked holdout and tradeable metrics.

Replays the historical panel chronologically (no peeking), scores each day with
forward-style rank IC and quintile spread, and judges promotion on holdout
tradeable spread — not holdout Sharpe alone.

Usage:
  python scripts/intelligence/walkforward_engine.py
  python scripts/intelligence/walkforward_engine.py --signal alpha --selection-frac 0.6
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
PANEL_PARQUET = REPO / "data" / "intelligence" / "historical" / "panel.parquet"
PANEL_CSV = REPO / "data" / "intelligence" / "historical" / "panel.csv.gz"
META_PATH = REPO / "data" / "intelligence" / "historical" / "panel_meta.json"
CONFIG_PATH = REPO / "config" / "mad_scientist_lab.json"
OUT_PATH = REPO / "data" / "intelligence" / "research" / "walkforward_latest.json"

sys.path.insert(0, str(REPO / "scripts"))

from intelligence.alpha.neutralize import quantile_spread, spearman_ic  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_config() -> dict:
    defaults = {
        "selection_frac": 0.6,
        "min_selection_days": 20,
        "min_holdout_days": 15,
        "min_breadth_per_day": 30,
    }
    if CONFIG_PATH.exists():
        try:
            defaults.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return defaults


def load_panel() -> pd.DataFrame:
    if PANEL_PARQUET.exists():
        df = pd.read_parquet(PANEL_PARQUET)
    elif PANEL_CSV.exists():
        df = pd.read_csv(PANEL_CSV, compression="gzip")
    else:
        raise FileNotFoundError("no panel — run panel_builder.py")
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def _signal_series(g: pd.DataFrame, signal: str) -> pd.Series:
    if signal == "alpha" and "alpha" in g.columns:
        return g["alpha"].astype(float)
    if signal == "edge" or "edge" not in g.columns:
        proba = g["pred_proba_up"].astype(float)
        pr = g["pred_ret"].astype(float)
        return (2.0 * proba - 1.0) * pr.abs()
    return g["edge"].astype(float)


def _score_day(g: pd.DataFrame, signal: str) -> dict | None:
    if len(g) < 8:
        return None
    fwd = g["y_ret"].astype(float)
    sig = _signal_series(g, signal)
    ic = spearman_ic(sig, fwd)
    spread = quantile_spread(sig, fwd)
    if not np.isfinite(ic) and not np.isfinite(spread):
        return None
    return {
        "ic": round(float(ic), 5) if np.isfinite(ic) else None,
        "quintile_spread": round(float(spread), 6) if np.isfinite(spread) else None,
        "breadth": int(len(g)),
    }


def _aggregate_daily(daily: list[dict]) -> dict:
    ics = [d["ic"] for d in daily if d.get("ic") is not None and np.isfinite(d["ic"])]
    spreads = [
        d["quintile_spread"] for d in daily
        if d.get("quintile_spread") is not None and np.isfinite(d["quintile_spread"])
    ]
    breadth = [d.get("breadth", 0) for d in daily]
    mean_ic = float(np.mean(ics)) if ics else None
    std_ic = float(np.std(ics, ddof=0)) if len(ics) > 1 else None
    icir = (mean_ic / std_ic) if (mean_ic is not None and std_ic) else None
    mean_spread = float(np.mean(spreads)) if spreads else None
    return {
        "mean_ic": round(mean_ic, 5) if mean_ic is not None else None,
        "icir": round(icir, 4) if icir is not None else None,
        "ic_hit_rate": round(float(np.mean([i > 0 for i in ics])), 4) if ics else None,
        "mean_quintile_spread": round(mean_spread, 6) if mean_spread is not None else None,
        "spread_positive_days": round(float(np.mean([s > 0 for s in spreads])), 4) if spreads else None,
        "n_days": len(daily),
        "mean_breadth": int(np.mean(breadth)) if breadth else 0,
    }


def split_windows(
    dates: list[str],
    *,
    selection_frac: float,
    holdout_locked: bool = True,
) -> tuple[list[str], list[str]]:
    """Chronological split; holdout tail is locked (never used for tuning)."""
    if not dates:
        return [], []
    split = max(1, int(len(dates) * selection_frac))
    if holdout_locked and split >= len(dates):
        split = max(1, len(dates) - 1)
    return dates[:split], dates[split:]


def promotion_verdict(holdout: dict, *, min_spread: float = 0.0) -> tuple[str, list[str]]:
    """Scientific verdict: promote only when tradeable spread clears the bar."""
    reasons: list[str] = []
    spread = holdout.get("mean_quintile_spread")
    mean_ic = holdout.get("mean_ic")
    n_days = holdout.get("n_days") or 0

    if n_days < 10:
        reasons.append(f"holdout_days={n_days}<10")
    if spread is None:
        reasons.append("holdout_spread_missing")
    elif spread <= min_spread:
        reasons.append(f"holdout_quintile_spread={spread}<={min_spread}")

    sharpe_proxy = None
    if spread is not None and holdout.get("icir") is not None:
        sharpe_proxy = holdout["icir"]
    if sharpe_proxy and sharpe_proxy > 0.5 and (spread or 0) <= 0:
        reasons.append("high_icir_but_negative_spread")

    if mean_ic is not None and mean_ic < 0:
        reasons.append(f"holdout_mean_ic={mean_ic}<0")

    if reasons:
        return "reject", reasons
    return "accept", ["holdout_spread_positive", "holdout_ic_ok"]


def run(
    *,
    signal: str = "alpha",
    selection_frac: float | None = None,
    rebuild_panel: bool = False,
    hypothesis_id: str | None = None,
) -> dict:
    cfg = _load_config()
    selection_frac = selection_frac if selection_frac is not None else float(cfg.get("selection_frac") or 0.6)

    from intelligence.historical.panel_builder import ensure_panel

    ensure_panel(force=rebuild_panel)

    try:
        df = load_panel()
    except FileNotFoundError as exc:
        doc = {"generatedAt": _now(), "ok": False, "message": str(exc)}
        _write_out(doc)
        return doc

    min_breadth = int(cfg.get("min_breadth_per_day") or 30)
    daily_all: list[dict] = []
    for d, g in df.groupby("date", sort=True):
        if len(g) < min_breadth:
            continue
        scored = _score_day(g, signal)
        if scored:
            daily_all.append({"date": str(d), **scored})

    if len(daily_all) < 20:
        doc = {
            "generatedAt": _now(),
            "ok": False,
            "message": f"too few scored days ({len(daily_all)})",
        }
        _write_out(doc)
        return doc

    dates = [d["date"] for d in daily_all]
    sel_dates, hold_dates = split_windows(dates, selection_frac=selection_frac, holdout_locked=True)
    sel_set, hold_set = set(sel_dates), set(hold_dates)

    sel_daily = [d for d in daily_all if d["date"] in sel_set]
    hold_daily = [d for d in daily_all if d["date"] in hold_set]

    selection = _aggregate_daily(sel_daily)
    holdout = _aggregate_daily(hold_daily)
    verdict_label, verdict_reasons = promotion_verdict(holdout)

    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "engine": "walkforward_engine",
        "hypothesisId": hypothesis_id,
        "signal": signal,
        "method": (
            f"Day-by-day replay on historical panel; selection first {selection_frac:.0%} "
            f"of days (locked holdout tail, no peeking)."
        ),
        "caveat": (
            "Historical walk-forward is a candidate generator — survivors must still prove "
            "forward on live paper. Promotion gate uses holdout quintile spread, not Sharpe."
        ),
        "panel": {"rows": int(len(df)), "meta": meta.get("walkforward")},
        "window": {
            "start": dates[0],
            "end": dates[-1],
            "nDays": len(dates),
            "selectionDays": len(sel_dates),
            "holdoutDays": len(hold_dates),
            "holdoutStart": hold_dates[0] if hold_dates else None,
            "holdoutEnd": hold_dates[-1] if hold_dates else None,
        },
        "selection": selection,
        "holdout": holdout,
        "verdict": verdict_label,
        "verdictReasons": verdict_reasons,
        "dailyTail": daily_all[-30:],
    }
    _write_out(doc)
    print(
        f"[walkforward-engine] signal={signal} sel_spread={selection.get('mean_quintile_spread')} "
        f"hold_spread={holdout.get('mean_quintile_spread')} verdict={verdict_label}",
        flush=True,
    )
    return doc


def _write_out(doc: dict) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def hypothesis_fingerprint(signal: str, selection_frac: float) -> str:
    raw = f"wf|{signal}|{selection_frac:.3f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Walk-forward engine — tradeable spread gate")
    ap.add_argument("--signal", default="alpha", choices=("alpha", "edge"))
    ap.add_argument("--selection-frac", type=float, default=0.0)
    ap.add_argument("--rebuild-panel", action="store_true")
    ap.add_argument("--hypothesis-id", default="")
    args = ap.parse_args()
    frac = args.selection_frac if args.selection_frac > 0 else None
    run(
        signal=args.signal,
        selection_frac=frac,
        rebuild_panel=args.rebuild_panel,
        hypothesis_id=args.hypothesis_id or None,
    )
