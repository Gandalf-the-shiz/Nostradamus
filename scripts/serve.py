"""Local Nostradamus server.

Serves the static front-end + a small JSON API on top of the existing
artefacts. Run:

    python scripts/serve.py            # http://127.0.0.1:8000
    python scripts/serve.py --port 4173

Endpoints
---------
GET  /                       static front-end (index.html)
GET  /api/health             { ok, version, decisions: {...} }
GET  /api/decisions          returns data/investor_v3/decisions.json
POST /api/retrain            launches train-investor-v3.py in background
GET  /api/retrain/status     { state, started_at, finished_at, returncode, log_tail }
GET  /api/trading/manifest   Robinhood Agents swing manifest
GET  /api/daytrade/manifest  Intraday aggressive manifest
GET  /api/reasoning/strategy Paper-trading reasoning agent strategy
GET  /api/brain/schedule     Market-aware scheduler state
POST /api/trading/ack        Record fill from external broker
POST /api/orchestrator/run   Full prep pipeline
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DECISIONS_PATH = ROOT / "data" / "investor_v3" / "decisions.json"
TRADING_MANIFEST = ROOT / "data" / "trading" / "robinhood_manifest.json"
TRADING_SIGNALS = ROOT / "data" / "trading" / "signals.json"
CONGRESS_SIGNALS = ROOT / "data" / "congress" / "signals_by_symbol.json"
CONGRESS_LEADERBOARD = ROOT / "data" / "congress" / "leaderboard.json"
CONGRESS_NOTABLE = ROOT / "data" / "congress" / "notable_trades.json"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
VERSION = "0.2.0"
MODEL_PATH = ROOT / "models" / "v3" / "investor" / "policy.joblib"
SENTIMENT_PATH = ROOT / "data" / "sentiment" / "per_symbol.json"
HIST_MANIFEST = ROOT / "data" / "historical" / "manifest.json"

# ── Default training command. Mirrors the canonical config we backtest with.
TRAIN_CMD = [
    sys.executable,
    str(ROOT / "scripts" / "train-investor-v3.py"),
    "--top-k", "5",
    "--max-position-frac", "0.20",
    "--max-gross-exposure", "0.90",
    "--kelly-scale", "0.5",
    "--cost-bps", "5",
    "--slippage-bps", "10",
    "--min-proba", "0.60",
    "--min-pred-ret", "0.020",
    "--min-price", "5",
    "--min-adv", "1000000",
    "--min-vol-20", "0.01",
    "--max-daily-ret", "0.20",
    "--policy-mode", "edge",
]

# ── In-memory job state. Single-slot — only one retrain at a time.
_job_lock = threading.Lock()
_job: dict = {
    "state": "idle",            # idle | running | done | failed
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "log_path": None,
    "pid": None,
}


def _file_meta(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _tail(path: Path, n: int = 40) -> list[str]:
    if not path or not Path(path).exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return [ln.rstrip("\n") for ln in lines[-n:]]
    except OSError:
        return []


def _run_training(log_path: Path) -> None:
    """Run the trainer as a subprocess and update _job state when done."""
    try:
        with open(log_path, "w", encoding="utf-8") as logf:
            logf.write(f"# nostradamus retrain @ {datetime.now(timezone.utc).isoformat()}\n")
            logf.write(f"# cmd: {' '.join(TRAIN_CMD)}\n\n")
            logf.flush()
            proc = subprocess.Popen(
                TRAIN_CMD,
                cwd=str(ROOT),
                stdout=logf,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with _job_lock:
                _job["pid"] = proc.pid
            rc = proc.wait()
        with _job_lock:
            _job["state"] = "done" if rc == 0 else "failed"
            _job["returncode"] = rc
            _job["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:  # pragma: no cover
        with _job_lock:
            _job["state"] = "failed"
            _job["returncode"] = -1
            _job["finished_at"] = datetime.now(timezone.utc).isoformat()
            _job["error"] = str(exc)


app = FastAPI(title="Nostradamus local server", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _last_nightly_log() -> dict:
    """Parse the most recent nightly-*.log to expose pipeline health."""
    logs = sorted(LOG_DIR.glob("nightly-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return {"exists": False}
    p = logs[0]
    out: dict = {
        "exists": True,
        "path": p.name,
        "modified_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
    }
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    # Parse our own marker lines written by nightly.ps1
    for line in text.splitlines():
        if line.startswith("# fetch exit code:"):
            try: out["fetch_rc"] = int(line.split(":", 1)[1].strip())
            except Exception: pass
        elif line.startswith("# train exit code:"):
            try: out["train_rc"] = int(line.split(":", 1)[1].strip())
            except Exception: pass
        elif line.startswith("# enrich exit code:"):
            try: out["enrich_rc"] = int(line.split(":", 1)[1].strip())
            except Exception: pass
    return out


def _last_bar_date() -> str | None:
    """Read manifest.json to expose the most recent OHLCV bar date."""
    if not HIST_MANIFEST.exists():
        return None
    try:
        m = json.loads(HIST_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # manifest schema varies; try common keys
    for k in ("last_bar_date", "latest_date", "max_date", "as_of", "updated_at"):
        v = m.get(k)
        if isinstance(v, str) and v:
            return v[:10]
    return None


def _pipeline_status() -> dict:
    return {
        "model": _file_meta(MODEL_PATH),
        "sentiment_cache": _file_meta(SENTIMENT_PATH),
        "last_bar_date": _last_bar_date(),
        "last_nightly": _last_nightly_log(),
    }


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": VERSION,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "decisions": _file_meta(DECISIONS_PATH),
        "job": {k: v for k, v in _job.items() if k != "log_path"},
        "pipeline": _pipeline_status(),
    }


@app.get("/api/status")
def status():
    """Alias of /api/health['pipeline'] for clients that just want pipeline state."""
    return _pipeline_status()


@app.get("/api/decisions")
def decisions():
    if not DECISIONS_PATH.exists():
        raise HTTPException(404, "decisions.json not found — run /api/retrain or the trainer")
    return FileResponse(
        DECISIONS_PATH,
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/retrain")
def retrain():
    with _job_lock:
        if _job["state"] == "running":
            raise HTTPException(409, "A retrain job is already running")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = LOG_DIR / f"retrain-{ts}.log"
        _job.update({
            "state": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "returncode": None,
            "log_path": str(log_path),
            "pid": None,
            "error": None,
        })
    t = threading.Thread(target=_run_training, args=(log_path,), daemon=True)
    t.start()
    return {"state": "running", "log": log_path.name}


@app.get("/api/retrain/status")
def retrain_status():
    with _job_lock:
        snapshot = dict(_job)
    log_path = snapshot.get("log_path")
    snapshot["log_tail"] = _tail(Path(log_path), n=50) if log_path else []
    return snapshot


# ── Bars (OHLCV) lookup from local data/historical/<sector>.json files. ─────

_SYM_INDEX: dict[str, Path] = {}
_SYM_INDEX_MTIME: float = 0.0
_BARS_LOCK = threading.Lock()


def _refresh_symbol_index() -> None:
    """Build (or rebuild) a symbol->sector-file index from data/historical."""
    global _SYM_INDEX, _SYM_INDEX_MTIME
    hist = ROOT / "data" / "historical"
    if not hist.exists():
        _SYM_INDEX = {}
        return
    latest = max((p.stat().st_mtime for p in hist.glob("*.json")), default=0.0)
    if latest == _SYM_INDEX_MTIME and _SYM_INDEX:
        return
    idx: dict[str, Path] = {}
    for fp in hist.glob("*.json"):
        if fp.name == "manifest.json":
            continue
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        stocks = (payload.get("stocks") or {}) if isinstance(payload, dict) else {}
        for sym in stocks.keys():
            idx[sym.upper()] = fp
    _SYM_INDEX = idx
    _SYM_INDEX_MTIME = latest


_LIVE_FETCH_LOCK = threading.Lock()
_LIVE_FETCH_MEMO: dict = {}
_LIVE_FETCH_TTL_S = 300.0  # cache live-fetched bars in-memory for 5 min


def _live_fetch_candles(sym: str, days: int = 400) -> list:
    """Fetch ~1y of daily OHLCV via yfinance for a single symbol.

    On-demand fallback when the symbol is not yet in the local lake, so the
    UI works for any US ticker even before the nightly batch runs. Cached
    in-memory and persisted into data/historical/_live.json.
    """
    now = time.time()
    with _LIVE_FETCH_LOCK:
        memo = _LIVE_FETCH_MEMO.get(sym)
        if memo and (now - memo[0]) < _LIVE_FETCH_TTL_S:
            return memo[1]
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return []
    try:
        df = yf.Ticker(sym).history(period=f"{max(60, days)}d", interval="1d", auto_adjust=False)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    candles: list = []
    for ts, row in df.iterrows():
        try:
            candles.append({
                "date": ts.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    with _LIVE_FETCH_LOCK:
        _LIVE_FETCH_MEMO[sym] = (now, candles)
    # Persist for the lake so future requests are instant and survive restart.
    try:
        live_fp = ROOT / "data" / "historical" / "_live.json"
        live_fp.parent.mkdir(parents=True, exist_ok=True)
        if live_fp.exists():
            try:
                payload = json.loads(live_fp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"sector": "_live", "stocks": {}}
        else:
            payload = {"sector": "_live", "stocks": {}}
        payload.setdefault("stocks", {})[sym] = {"candles": candles}
        live_fp.write_text(json.dumps(payload), encoding="utf-8")
        global _SYM_INDEX_MTIME
        _SYM_INDEX[sym] = live_fp
        _SYM_INDEX_MTIME = 0.0  # force rescan on next call
    except OSError:
        pass
    return candles


def _load_candles(sym: str) -> tuple[list, str | None, str]:
    """Return (candles, sector_file, source) where source is 'local' | 'live' | 'none'."""
    with _BARS_LOCK:
        _refresh_symbol_index()
        fp = _SYM_INDEX.get(sym)
    candles: list = []
    sector_file: str | None = None
    if fp is not None:
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            stocks = (payload.get("stocks") or {}) if isinstance(payload, dict) else {}
            candles = (stocks.get(sym) or {}).get("candles") or []
            sector_file = fp.name
        except (OSError, json.JSONDecodeError):
            candles = []
    if candles:
        return candles, sector_file, "local"
    candles = _live_fetch_candles(sym)
    if candles:
        return candles, "_live.json", "live"
    return [], None, "none"


@app.get("/api/bars")
def bars(symbol: str, limit: int = 252):
    """Return daily OHLCV candles for a symbol.

    Query: symbol=AAPL, limit=252 (last N candles; 0 = all).
    Falls back to a live yfinance fetch when the symbol isn't in local cache.
    """
    sym = symbol.strip().upper()
    if not sym or not sym.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid symbol")
    candles, sector_file, source = _load_candles(sym)
    if not candles:
        raise HTTPException(404, f"no bars for {sym}")
    if limit and limit > 0:
        candles = candles[-limit:]
    return {
        "symbol": sym,
        "sector_file": sector_file,
        "source": source,
        "count": len(candles),
        "candles": candles,
    }


@app.get("/api/quote")
def quote(symbol: str):
    """Latest close + day change for a symbol, computed from local bars (or live)."""
    sym = symbol.strip().upper()
    if not sym or not sym.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid symbol")
    candles, _sector_file, source = _load_candles(sym)
    if not candles:
        raise HTTPException(404, f"no quote for {sym}")
    last = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else last
    prev_close = float(prev.get("close") or 0.0)
    last_close = float(last.get("close") or 0.0)
    change = last_close - prev_close
    pct = (change / prev_close * 100.0) if prev_close else 0.0
    return {
        "symbol": sym,
        "source": source,
        "date": last.get("date"),
        "open": last.get("open"),
        "high": last.get("high"),
        "low": last.get("low"),
        "close": last_close,
        "previousClose": prev_close,
        "change": change,
        "changePercent": pct,
        "volume": last.get("volume"),
    }


# ── News + sentiment lookup (Yahoo RSS headlines, FinBERT cache). ───────────

@app.get("/api/news")
def news(symbol: str, max_headlines: int = 6):
    """Recent Yahoo RSS headlines for a symbol, with cached FinBERT scores when available.

    Returns: { symbol, headlines: [{title, published, score?, label?}], sentiment: {...} | null }
    """
    sym = symbol.strip().upper()
    if not sym or not sym.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid symbol")
    # Import lazily so server boot does not pay the cost.
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from enrich_decisions import fetch_headlines  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise HTTPException(500, f"news module unavailable: {exc}")

    headlines = fetch_headlines(sym, max_headlines=max(1, min(max_headlines, 20)))

    # Merge FinBERT cache (per-symbol JSON written by enrich_decisions.py).
    cache: dict = {}
    if SENTIMENT_PATH.exists():
        try:
            cache = json.loads(SENTIMENT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    sentiment = cache.get(sym)  # already-aggregated summary if recently enriched
    return {
        "symbol": sym,
        "headlines": headlines,
        "sentiment": sentiment,
    }


# ── Trading / Robinhood Agents handoff ───────────────────────────────────────

@app.get("/api/trading/manifest")
def trading_manifest():
    if not TRADING_MANIFEST.exists():
        raise HTTPException(404, "robinhood_manifest.json missing — run generate_trade_signals.py")
    return FileResponse(TRADING_MANIFEST, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/trading/signals")
def trading_signals():
    if not TRADING_SIGNALS.exists():
        raise HTTPException(404, "signals.json missing — run generate_trade_signals.py")
    return FileResponse(TRADING_SIGNALS, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/trading/config")
def trading_config():
    return {
        "brokerMode": os.getenv("BROKER_MODE", "paper"),
        "dryRun": os.getenv("BROKER_MODE", "paper") in {"paper", "dry_run", "manifest_only"},
        "manifest": _file_meta(TRADING_MANIFEST),
        "maxGrossExposure": float(os.getenv("BROKER_MAX_GROSS_EXPOSURE", "0.90")),
        "maxPositionFrac": float(os.getenv("BROKER_MAX_POSITION_FRAC", "0.20")),
        "minProba": float(os.getenv("BROKER_MIN_PROBA", "0.60")),
        "robinhoodPrep": True,
    }


@app.post("/api/trading/ack")
async def trading_ack(body: dict):
    """Record execution feedback from Robinhood Agents (or manual tester)."""
    from broker.adapter import ExecutionReport, RobinhoodAgentBridge

    order_id = str(body.get("order_id") or "")
    if not order_id:
        raise HTTPException(400, "order_id required")
    report = ExecutionReport(
        order_id=order_id,
        status=str(body.get("status") or "filled"),
        filled_qty=float(body.get("filled_qty") or 0),
        filled_notional=float(body.get("filled_notional") or 0),
        avg_price=float(body["avg_price"]) if body.get("avg_price") is not None else None,
        message=str(body.get("message") or ""),
        broker=str(body.get("broker") or "robinhood_agents"),
    )
    RobinhoodAgentBridge().record_ack(report)
    return {"ok": True, "recorded": order_id}


@app.post("/api/trading/generate")
def trading_generate():
    """Regenerate Robinhood manifest from latest decisions."""
    log_path = LOG_DIR / f"signals-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_trade_signals.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "generate_trade_signals failed")
    return {"ok": True, "manifest": _file_meta(TRADING_MANIFEST)}


@app.get("/api/congress/signals")
def congress_signals():
    if not CONGRESS_SIGNALS.exists():
        raise HTTPException(404, "run fetch-congress-trades.py first")
    return FileResponse(CONGRESS_SIGNALS, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/congress/leaderboard")
def congress_leaderboard():
    if not CONGRESS_LEADERBOARD.exists():
        raise HTTPException(404, "run fetch-congress-trades.py first")
    return FileResponse(CONGRESS_LEADERBOARD, media_type="application/json")


@app.get("/api/congress/notable")
def congress_notable():
    """Recent trades by watchlist politicians (Pelosi, Tuberville, etc.)."""
    if not CONGRESS_NOTABLE.exists():
        raise HTTPException(404, "run fetch-congress-trades.py first")
    return FileResponse(CONGRESS_NOTABLE, media_type="application/json")


@app.get("/api/congress/symbol/{symbol}")
def congress_symbol(symbol: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    from congress_signals import get_symbol_signal

    sig = get_symbol_signal(symbol.upper())
    if not sig:
        raise HTTPException(404, f"no congressional signal for {symbol.upper()}")
    return sig


@app.post("/api/congress/refresh")
def congress_refresh():
    log_path = LOG_DIR / f"congress-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch-congress-trades.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "fetch-congress-trades failed")
    return {"ok": True, "signals": _file_meta(CONGRESS_SIGNALS)}


@app.get("/api/learning/status")
def learning_status():
    path = ROOT / "data" / "learning" / "harness_state.json"
    if not path.exists():
        return {"phase": "idle", "message": "run learning_harness.py"}
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


REASONING_STRATEGY = ROOT / "data" / "reasoning" / "strategy.json"
REASONING_JOURNAL = ROOT / "data" / "reasoning" / "journal.jsonl"
DAYTRADE_MANIFEST = ROOT / "data" / "trading" / "daytrade_manifest.json"
BRAIN_SCHEDULE = ROOT / "data" / "learning" / "schedule.json"


@app.get("/api/reasoning/strategy")
def reasoning_strategy():
    if not REASONING_STRATEGY.exists():
        raise HTTPException(404, "run reasoning_agent.py --tick first")
    return JSONResponse(json.loads(REASONING_STRATEGY.read_text(encoding="utf-8")))


@app.get("/api/reasoning/journal")
def reasoning_journal(limit: int = 30):
    if not REASONING_JOURNAL.exists():
        return {"entries": []}
    lines = REASONING_JOURNAL.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for ln in lines[-max(1, min(limit, 200)) :]:
        try:
            entries.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return {"entries": entries}


@app.post("/api/reasoning/tick")
def reasoning_tick():
    log_path = LOG_DIR / f"reasoning-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "reasoning_agent.py"), "--tick"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "reasoning_agent failed")
    return {"ok": True, "strategy": _file_meta(REASONING_STRATEGY)}


@app.get("/api/daytrade/manifest")
def daytrade_manifest():
    if not DAYTRADE_MANIFEST.exists():
        raise HTTPException(404, "run generate_daytrade_signals.py first")
    return FileResponse(DAYTRADE_MANIFEST, media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.post("/api/daytrade/generate")
def daytrade_generate():
    log_path = LOG_DIR / f"daytrade-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_daytrade_signals.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-500:] or "generate_daytrade_signals failed")
    return {"ok": True, "manifest": _file_meta(DAYTRADE_MANIFEST)}


@app.get("/api/brain/schedule")
def brain_schedule():
    if BRAIN_SCHEDULE.exists():
        return JSONResponse(json.loads(BRAIN_SCHEDULE.read_text(encoding="utf-8")))
    return {"recommendedMode": "idle", "message": "run learning_scheduler.py --tick"}


@app.post("/api/brain/tick")
def brain_tick():
    log_path = LOG_DIR / f"brain-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "learning_scheduler.py"), "--tick"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-800:] or "scheduler tick failed")
    sched = json.loads(BRAIN_SCHEDULE.read_text(encoding="utf-8")) if BRAIN_SCHEDULE.exists() else {}
    return {"ok": True, "schedule": sched}


@app.post("/api/learning/run")
def learning_run():
    log_path = LOG_DIR / f"harness-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    skip = os.getenv("SKIP_PREDICTOR_TRAIN", "").lower() in {"1", "true", "yes"}
    cmd = [sys.executable, str(ROOT / "scripts" / "learning_harness.py"), "--once"]
    if skip:
        cmd.append("--skip-predictor")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-800:] or "learning_harness failed")
    return {"ok": True, "log": log_path.name}


PRED_META = ROOT / "models" / "v3" / "predictor" / "metadata.json"
PRED_CHAMP = ROOT / "models" / "v3" / "predictor" / "metadata_champion.json"
INV_META = ROOT / "models" / "v3" / "investor" / "metadata.json"
INV_SUMMARY = ROOT / "data" / "investor_v3" / "summary.json"
LIVE_PRED = ROOT / "data" / "predictions_v3" / "live.csv"
HARNESS_STATE = ROOT / "data" / "learning" / "harness_state.json"
NPU_STATUS = ROOT / "data" / "learning" / "npu_status.json"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _health_check(check_id: str, label: str, ok: bool, detail: str, **extra) -> dict:
    return {"id": check_id, "label": label, "ok": ok, "detail": detail, **extra}


@app.get("/api/models/overview")
def models_overview():
    """Single-pane metrics for Predictor + Investor + pipeline health."""
    pred = _read_json(PRED_META) or {}
    champ = _read_json(PRED_CHAMP) or pred
    inv_meta = _read_json(INV_META) or {}
    inv_sum = _read_json(INV_SUMMARY) or inv_meta.get("summary") or {}
    pt = (pred.get("metrics") or {}).get("test") or {}
    ct = (champ.get("metrics") or {}).get("test") or pt
    harness = _read_json(HARNESS_STATE) or {}
    npu = _read_json(NPU_STATUS) or {}
    sched = _read_json(BRAIN_SCHEDULE) if BRAIN_SCHEDULE.exists() else {}
    hist = _read_json(HIST_MANIFEST) or {}

    hist_ok = bool(hist.get("totalTickers", 0) > 1000)
    live_ok = LIVE_PRED.exists() and LIVE_PRED.stat().st_size > 100
    dec_ok = DECISIONS_PATH.exists()
    swing_ok = TRADING_MANIFEST.exists()
    day_ok = DAYTRADE_MANIFEST.exists()
    reason_ok = REASONING_STRATEGY.exists()

    checks = [
        _health_check("historical", "Historical OHLCV", hist_ok,
                      f"{hist.get('totalTickers', 0):,} tickers, {hist.get('totalDataPoints', 0):,} bars"),
        _health_check("live_predictions", "Live ML inference", live_ok,
                      "live.csv ready" if live_ok else "run generate_live_predictions.py"),
        _health_check("investor_decisions", "Investor decisions", dec_ok,
                      _file_meta(DECISIONS_PATH).get("modified_at", "missing")),
        _health_check("swing_manifest", "Swing Robinhood manifest", swing_ok,
                      _file_meta(TRADING_MANIFEST).get("modified_at", "missing")),
        _health_check("daytrade_manifest", "Daytrade manifest", day_ok,
                      _file_meta(DAYTRADE_MANIFEST).get("modified_at", "missing")),
        _health_check("reasoning_agent", "Reasoning agent", reason_ok,
                      _file_meta(REASONING_STRATEGY).get("modified_at", "missing")),
        _health_check("continuous_brain", "Scheduler / brain",
                      bool(sched.get("recommendedMode")),
                      sched.get("recommendedMode", "idle")),
        _health_check("npu_runtime", "NPU / ONNX runtime", True,
                      (lambda p: f"{p} ({'accelerated' if p not in ('CPUExecutionProvider', 'AzureExecutionProvider') else 'CPU fallback'})")(
                          npu.get("primary", "CPUExecutionProvider"))),
    ]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "predictor": {
            "version": pred.get("version"),
            "trainedAt": pred.get("trained_at"),
            "features": pred.get("feature_count"),
            "test": {
                "accuracy": pt.get("accuracy"),
                "auc": pt.get("auc"),
                "f1": pt.get("f1"),
                "regMae": pt.get("reg_mae"),
                "n": pt.get("n"),
            },
            "champion": {
                "accuracy": ct.get("accuracy"),
                "auc": ct.get("auc"),
            },
        },
        "investor": {
            "version": inv_meta.get("version"),
            "trainedAt": inv_meta.get("trained_at"),
            "totalReturnPct": inv_sum.get("total_return_pct"),
            "sharpe": inv_sum.get("annualized_sharpe"),
            "maxDrawdownPct": inv_sum.get("max_drawdown_pct"),
            "winRatePct": inv_sum.get("win_rate_pct"),
            "trades": inv_sum.get("trades"),
        },
        "pipeline": {
            "harnessPhase": harness.get("phase"),
            "harnessMode": harness.get("mode"),
            "schedule": sched,
            "npu": npu,
            "historical": {
                "tickers": hist.get("totalTickers"),
                "lastIncremental": hist.get("lastIncrementalFetch"),
            },
        },
        "healthChecks": checks,
        "healthScore": round(100 * sum(1 for c in checks if c["ok"]) / max(len(checks), 1)),
    }


V2_META = ROOT / "models" / "v2" / "metadata.json"
V2_PREV = ROOT / "models" / "v2" / "metadata_prev.json"
ACCURACY_LOG = ROOT / "data" / "accuracy" / "accuracy-log.json"
PAPER_SUMMARY = ROOT / "data" / "paper_agent" / "summary.json"
PROMO_HISTORY = ROOT / "data" / "learning" / "promotion-history.json"
REASON_PORTFOLIO = ROOT / "data" / "reasoning" / "paper_portfolio.json"


@app.get("/api/command-center")
def command_center():
    """Full breakdown of every ML model feeding predictions, accuracy, and trends."""
    pred = _read_json(PRED_META) or {}
    champ = _read_json(PRED_CHAMP) or pred
    inv_meta = _read_json(INV_META) or {}
    inv_sum = _read_json(INV_SUMMARY) or inv_meta.get("summary") or {}
    v2 = _read_json(V2_META) or {}
    v2_prev = _read_json(V2_PREV) or {}
    acc_log = _read_json(ACCURACY_LOG) or {}
    paper = _read_json(PAPER_SUMMARY) or {}
    reason = _read_json(REASONING_STRATEGY) or {}
    reason_port = _read_json(REASON_PORTFOLIO) or {}
    npu = _read_json(NPU_STATUS) or {}
    sched = _read_json(BRAIN_SCHEDULE) if BRAIN_SCHEDULE.exists() else {}
    harness = _read_json(HARNESS_STATE) or {}

    pt = (pred.get("metrics") or {}).get("test") or {}
    pv = (pred.get("metrics") or {}).get("val") or {}
    ct = (champ.get("metrics") or {}).get("test") or pt

    # V2 live accuracy trend (filter out empty days)
    acc_entries = [
        {"date": e.get("date"), "hitRate": e.get("hitRate"), "mae": e.get("regressionMAE"), "n": e.get("total")}
        for e in (acc_log.get("entries") or [])
        if e.get("hitRate") is not None and (e.get("total") or 0) > 0
    ]

    live_count = 0
    if LIVE_PRED.exists():
        try:
            live_count = max(0, sum(1 for _ in LIVE_PRED.open(encoding="utf-8")) - 1)
        except OSError:
            live_count = 0

    models = [
        {
            "id": "predictor_v3",
            "name": "Predictor v3",
            "role": "Next-day direction + return (core)",
            "architecture": pred.get("architecture", "HGB x5 stacked + isotonic + HGBR head"),
            "status": "champion",
            "features": pred.get("feature_count"),
            "trainedAt": pred.get("trained_at"),
            "metrics": [
                {"label": "Accuracy", "value": pt.get("accuracy"), "fmt": "pct"},
                {"label": "AUC", "value": pt.get("auc"), "fmt": "num3"},
                {"label": "F1", "value": pt.get("f1"), "fmt": "num3"},
                {"label": "Return MAE", "value": pt.get("reg_mae"), "fmt": "num4"},
                {"label": "Brier", "value": pt.get("brier"), "fmt": "num3"},
                {"label": "Test samples", "value": pt.get("n"), "fmt": "int"},
            ],
            "valAccuracy": pv.get("accuracy"),
            "championAuc": ct.get("auc"),
            "liveCount": live_count,
            "retrain": "Weekly (Sunday deep train)",
        },
        {
            "id": "investor_v3",
            "name": "Investor v3",
            "role": "Portfolio allocator (fractional-Kelly)",
            "architecture": inv_meta.get("architecture", "HGBR policy + Kelly allocator"),
            "status": "active",
            "trainedAt": inv_meta.get("trained_at"),
            "metrics": [
                {"label": "Return", "value": inv_sum.get("total_return_pct"), "fmt": "pctRaw"},
                {"label": "Sharpe", "value": inv_sum.get("annualized_sharpe"), "fmt": "num2"},
                {"label": "Win rate", "value": inv_sum.get("win_rate_pct"), "fmt": "pctRaw"},
                {"label": "Max DD", "value": inv_sum.get("max_drawdown_pct"), "fmt": "pctRaw"},
                {"label": "Trades", "value": inv_sum.get("trades"), "fmt": "int"},
                {"label": "Days", "value": inv_sum.get("trading_days"), "fmt": "int"},
            ],
            "retrain": "Daily (post-close)",
        },
        {
            "id": "v2_predictor",
            "name": "V2 Predictor",
            "role": "Browser/CI daily ensemble",
            "architecture": v2.get("architecture", "HGB dual-head"),
            "status": "ci",
            "features": v2.get("featureCount"),
            "trainedAt": v2.get("trainedAt"),
            "metrics": [
                {"label": "Accuracy", "value": (v2.get("testMetrics") or {}).get("accuracy"), "fmt": "pct"},
                {"label": "AUC", "value": (v2.get("testMetrics") or {}).get("auc"), "fmt": "num3"},
                {"label": "F1", "value": (v2.get("testMetrics") or {}).get("f1"), "fmt": "num3"},
                {"label": "Return MAE", "value": (v2.get("testMetrics") or {}).get("reg_mae"), "fmt": "num4"},
                {"label": "Live 7d hit", "value": (acc_log.get("rolling") or {}).get("7day"), "fmt": "pct"},
                {"label": "Live 30d hit", "value": (acc_log.get("rolling") or {}).get("30day"), "fmt": "pct"},
            ],
            "prevAccuracy": (v2_prev.get("testMetrics") or {}).get("accuracy"),
            "retrain": "Weekly + auto-retrain when <53%",
        },
        {
            "id": "paper_agent",
            "name": "Paper Agent",
            "role": "Online SGD trade-taker",
            "architecture": paper.get("model", "SGD logistic v1"),
            "status": "online",
            "trainedAt": paper.get("generatedAt"),
            "metrics": [
                {"label": "Return", "value": paper.get("totalReturnPct"), "fmt": "pctRaw"},
                {"label": "Max DD", "value": paper.get("maxDrawdownPct"), "fmt": "pctRaw"},
                {"label": "Trades", "value": paper.get("tradeCount"), "fmt": "int"},
                {"label": "Early hit", "value": paper.get("preUpdateHitRateEarly5"), "fmt": "pct"},
                {"label": "Late hit", "value": paper.get("preUpdateHitRateLate5"), "fmt": "pct"},
                {"label": "Learn delta", "value": paper.get("onlineLearningDelta"), "fmt": "num3"},
            ],
            "retrain": "Daily online update",
        },
        {
            "id": "reasoning_agent",
            "name": "Reasoning Agent",
            "role": (lambda b: "NPU LLM strategist + paper book" if b == "genai"
                     else "Template strategist + paper book (no LLM)")(reason.get("llmBackend", "template")),
            "architecture": f"LLM ({reason.get('llmBackend', 'template')})",
            "status": "live" if reason else "idle",
            "trainedAt": reason.get("updatedAt"),
            "metrics": [
                {"label": "Watchlist", "value": len(reason.get("watchlist") or []), "fmt": "int"},
                {"label": "Positions", "value": len((reason_port.get("positions") or {})), "fmt": "int"},
                {"label": "Paper cash", "value": reason_port.get("cash"), "fmt": "usd"},
                {"label": "Max pos", "value": reason.get("maxPositions"), "fmt": "int"},
                {"label": "Risk budget", "value": reason.get("riskBudget"), "fmt": "num2"},
            ],
            "narrative": reason.get("narrative"),
            "retrain": "Every 15 min (RTH)",
        },
    ]

    ov = models_overview()

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "models": models,
        "trends": {
            "v2Accuracy": acc_entries,
            "v2Rolling": acc_log.get("rolling") or {},
            "investorEquity": _investor_equity_series(),
        },
        "healthChecks": ov.get("healthChecks", []),
        "healthScore": ov.get("healthScore", 0),
        "pipeline": {
            "harnessPhase": harness.get("phase"),
            "harnessMode": harness.get("mode"),
            "session": sched.get("session"),
            "mode": sched.get("recommendedMode"),
            "npu": npu.get("primary", "CPUExecutionProvider"),
            "npuAvailable": npu.get("available", []),
        },
    }


def _investor_equity_series(max_points: int = 120) -> list:
    dec = _read_json(DECISIONS_PATH)
    if not dec:
        return []
    curve = dec.get("equity_curve") or []
    if not curve:
        return []
    step = max(1, len(curve) // max_points)
    return [
        {"date": p.get("date"), "equity": p.get("equity")}
        for p in curve[::step]
        if p.get("date") and p.get("date") != "FINAL"
    ]


@app.get("/api/predictions/live")
def predictions_live(limit: int = 100):
    if not LIVE_PRED.exists():
        raise HTTPException(404, "live.csv missing — run generate_live_predictions.py")
    try:
        import pandas as pd

        df = pd.read_csv(LIVE_PRED)
        if df.empty:
            return {"items": [], "count": 0}
        df["edge"] = (df["pred_proba_up"].astype(float) - 0.5) * 2.0 * df["pred_ret"].astype(float).abs()
        df = df.sort_values("edge", ascending=False).head(max(1, min(limit, 500)))
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "count": int(len(df)),
            "items": df.to_dict(orient="records"),
        }
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/pipeline/health")
def pipeline_health():
    ov = models_overview()
    return {"checks": ov["healthChecks"], "healthScore": ov["healthScore"], "generatedAt": ov["generatedAt"]}


@app.post("/api/chat")
async def chat(body: dict):
    """NPU-backed (or template) chat about ML agent findings."""
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    history = body.get("history") or []

    ov = models_overview()
    strategy = _read_json(REASONING_STRATEGY) or {}
    context_lines = [
        "You are Nostradamus, an assistant explaining local ML trading agents (paper only, not financial advice).",
        f"Predictor test accuracy: {ov['predictor']['test'].get('accuracy')}, AUC: {ov['predictor']['test'].get('auc')}.",
        f"Investor backtest return %: {ov['investor'].get('totalReturnPct')}, Sharpe: {ov['investor'].get('sharpe')}.",
        f"Pipeline health score: {ov.get('healthScore')}/100.",
        f"Reasoning watchlist: {', '.join(strategy.get('watchlist') or [])}.",
        f"Strategy narrative: {(strategy.get('narrative') or '')[:500]}",
    ]
    for h in history[-6:]:
        role = h.get("role", "user")
        content = str(h.get("content", ""))[:400]
        context_lines.append(f"{role}: {content}")
    context_lines.append(f"user: {message}")
    context_lines.append("assistant:")

    from npu_llm import complete

    reply, backend = complete("\n".join(context_lines), max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "600")))
    return {"reply": reply, "backend": backend, "generatedAt": datetime.now(timezone.utc).isoformat()}


@app.post("/api/orchestrator/run")
def orchestrator_run():
    """Run the full prep pipeline (feeds → macro → regime → investor → signals)."""
    log_path = LOG_DIR / f"orchestrator-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "orchestrator.py"), "--skip-train-predictor"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr[-800:] or "orchestrator failed")
    return {"ok": True, "log": log_path.name}


# ── Static front-end (mounted last so /api/* wins).
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn
    print(f"Nostradamus local server -> http://{args.host}:{args.port}")
    print(f"  static root : {ROOT}")
    print(f"  decisions   : {DECISIONS_PATH}")
    uvicorn.run(
        "scripts.serve:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
