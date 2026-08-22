"""Two-product scoreboard: long book vs 4 ETFs, and cash-neutral vs T-bills.

Never invents returns. If a markable series is missing, the block is
``{ available: false, reason: "..." }``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_PATH = REPO / "data" / "benchmark" / "scoreboard.json"
HIST_DIR = REPO / "data" / "historical"
ETF_SYMS = ("SPY", "QQQ", "DIA", "IWM")
PAUSED_PATH = REPO / "data" / "PAUSED.txt"

SKIP_HIST_META = frozenset({
    "manifest.json",
    "multiyear-coverage.json",
    "stooq-bulk-coverage.json",
    "_live.json",
})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _etf_closes() -> dict[str, list[dict]]:
    """Best-effort ETF close series from historical shards. Empty if not on disk."""
    found: dict[str, list[dict]] = {}
    if not HIST_DIR.exists():
        return found
    want = {s.upper() for s in ETF_SYMS}
    for fp in HIST_DIR.glob("*.json"):
        if fp.name in SKIP_HIST_META or fp.name.startswith("manifest"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            su = str(sym).upper()
            if su not in want or su in found:
                continue
            candles = (payload or {}).get("candles") or []
            series = []
            for c in candles:
                if not isinstance(c, dict):
                    continue
                d, px = c.get("date"), c.get("close")
                try:
                    px_f = float(px)
                except (TypeError, ValueError):
                    continue
                if d and px_f > 0:
                    series.append({"date": str(d)[:10], "close": px_f})
            if series:
                found[su] = series
        if len(found) == len(want):
            break
    return found


def _long_equity_series() -> list[dict]:
    """Look for a markable long-product equity curve. Do not invent one."""
    # Only the long-ETF product curve. Investor v3 decisions.json is a backtest
    # playback — using it here would present July as today.
    candidates = [
        REPO / "data" / "intelligence" / "alpha" / "long_equity.json",
        REPO / "data" / "benchmark" / "long_equity.json",
    ]
    for path in candidates:
        doc = _load(path)
        if not doc:
            continue
        curve = doc.get("equity") or doc.get("equity_curve") or []
        if isinstance(curve, list) and len(curve) >= 2:
            out = []
            for p in curve:
                if not isinstance(p, dict):
                    continue
                if p.get("date") in (None, "FINAL"):
                    continue
                if p.get("equity") is None:
                    continue
                out.append({"date": str(p["date"])[:10], "equity": float(p["equity"])})
            if len(out) >= 2:
                return out
    return []


def _window_return(series: list[dict], start: str, end: str, value_key: str) -> float | None:
    by_date = {p["date"]: p[value_key] for p in series}
    if start not in by_date or end not in by_date:
        return None
    a, b = float(by_date[start]), float(by_date[end])
    if a <= 0:
        return None
    return b / a - 1.0


def _score_long_vs_etfs() -> dict:
    long_eq = _long_equity_series()
    etfs = _etf_closes()
    if not long_eq:
        return {
            "available": False,
            "reason": "no markable long-ETF equity series yet — book_long.json is a snapshot, not a curve",
            "benchmarks": list(ETF_SYMS),
        }
    if not etfs:
        return {
            "available": False,
            "reason": "SPY/QQQ/DIA/IWM candles not on disk — will not invent ETF returns",
            "benchmarks": list(ETF_SYMS),
            "nLongPoints": len(long_eq),
        }
    start, end = long_eq[0]["date"], long_eq[-1]["date"]
    long_ret = _window_return(long_eq, start, end, "equity")
    vs = {}
    for sym in ETF_SYMS:
        series = etfs.get(sym)
        if not series:
            vs[sym] = {"available": False, "reason": f"{sym} series missing"}
            continue
        etf_ret = _window_return(series, start, end, "close")
        if etf_ret is None or long_ret is None:
            vs[sym] = {"available": False, "reason": f"no overlapping {start}→{end} marks"}
            continue
        vs[sym] = {
            "available": True,
            "etfReturn": round(etf_ret, 6),
            "longReturn": round(long_ret, 6),
            "beat": bool(long_ret > etf_ret),
        }
    marked = [v for v in vs.values() if v.get("available")]
    beat_all = bool(marked) and all(v.get("beat") for v in marked)
    return {
        "available": bool(marked),
        "window": {"start": start, "end": end, "nDays": len(long_eq)},
        "longReturn": round(long_ret, 6) if long_ret is not None else None,
        "vs": vs,
        "beatAllFour": beat_all,
        "verdict": "beats SPY/QQQ/DIA/IWM" if beat_all else (
            "does not beat all four ETFs" if marked else "incomplete ETF marks"
        ),
    }


def _score_neutral_vs_cash() -> dict:
    """T-bill comparison only when a clean cash series exists. Never invent."""
    tbill = REPO / "data" / "benchmark" / "tbill.json"
    if not tbill.exists():
        return {
            "available": False,
            "reason": "no clean T-bill series yet (data/benchmark/tbill.json missing) — will not invent cash returns",
        }
    return {
        "available": False,
        "reason": "T-bill file present but no markable neutral equity series wired yet — will not invent returns",
    }


def run() -> dict:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    paused = PAUSED_PATH.exists()
    long_vs = _score_long_vs_etfs()
    cash = _score_neutral_vs_cash()
    generated = _now()
    doc = {
        "generatedAt": generated,
        "ok": True,
        "paused": paused,
        "stale": True if paused else False,
        "longVsEtfs": long_vs,
        "neutralVsCash": cash,
        "note": "Forward paper is the only scoreboard. Missing series stay unavailable.",
    }
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(
        f"[benchmark] long_available={long_vs.get('available')} "
        f"cash_available={cash.get('available')} paused={paused}",
        flush=True,
    )
    return doc


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
