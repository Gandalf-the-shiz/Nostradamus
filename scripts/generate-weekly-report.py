#!/usr/bin/env python3
"""
scripts/generate-weekly-report.py
Weekly Intelligence Report Generator — Phase 10.

Reads:
  - Latest predictions from data/predictions/
  - Accuracy log from data/accuracy/accuracy-log.json
  - Model metadata from models/v2/metadata.json

Generates data/reports/weekly/YYYY-WW.json with:
  - Top 10 bullish / bearish picks
  - Sector rotation summary
  - Model performance (7d, 30d, 90d rolling)
  - Confidence distribution

Run automatically by .github/workflows/weekly-report.yml every Sunday at 5 AM UTC.
Can also be run manually: python scripts/generate-weekly-report.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# ─── Paths ────────────────────────────────────────────────────

PREDICTIONS_DIR  = Path("data/predictions")
ACCURACY_LOG     = Path("data/accuracy/accuracy-log.json")
MODEL_METADATA   = Path("models/v2/metadata.json")
REPORTS_DIR      = Path("data/reports/weekly")

# ─── Sector lookup ─────────────────────────────────────────────

# Stock symbol → GICS sector mapping (abbreviated — add more as needed)
SECTOR_LOOKUP = {
    "AAPL":  "Technology",    "GOOGL": "Technology",   "MSFT":  "Technology",
    "AMZN":  "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "META":  "Technology",    "NVDA":  "Technology",   "NFLX":  "Communication Services",
    "JPM":   "Financials",    "V":     "Financials",   "JNJ":   "Healthcare",
    "PFE":   "Healthcare",    "XOM":   "Energy",       "CVX":   "Energy",
    "GS":    "Financials",    "BAC":   "Financials",   "WMT":   "Consumer Staples",
    "KO":    "Consumer Staples", "DIS": "Communication Services", "BA": "Industrials",
}

# ─── Helpers ───────────────────────────────────────────────────

def iso_week_label(dt: datetime) -> str:
    """Return 'YYYY-Www' ISO week label, e.g. '2026-W15'."""
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def load_predictions() -> list[dict]:
    """Load all prediction files from data/predictions/."""
    preds = []
    if not PREDICTIONS_DIR.exists():
        return preds

    for fpath in sorted(PREDICTIONS_DIR.glob("*.json")):
        try:
            with open(fpath) as f:
                data = json.load(f)
            # Support both list and dict with a "predictions" key
            if isinstance(data, list):
                preds.extend(data)
            elif isinstance(data, dict) and "predictions" in data:
                preds.extend(data["predictions"])
        except Exception as e:
            print(f"  Warning: could not read {fpath}: {e}", file=sys.stderr)

    return preds


def load_accuracy_log() -> list[dict]:
    try:
        with open(ACCURACY_LOG) as f:
            data = json.load(f)
        return data.get("entries", [])
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"  Warning: could not read accuracy log: {e}", file=sys.stderr)
        return []


def load_model_metadata() -> dict:
    try:
        with open(MODEL_METADATA) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  Warning: could not read model metadata: {e}", file=sys.stderr)
        return {}


def rolling_performance(entries: list[dict], days: int) -> dict:
    """Compute hit rate over the last `days` calendar days."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    recent = []
    for e in entries:
        try:
            dt = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            if dt >= cutoff:
                recent.append(e)
        except Exception:
            pass
    if not recent:
        return {"hitRate": None, "totalPredictions": 0}
    correct = sum(1 for e in recent if e.get("isCorrect", False))
    return {
        "hitRate": round(correct / len(recent), 4),
        "totalPredictions": len(recent),
    }


def confidence_distribution(preds: list[dict]) -> dict:
    """Bucket predictions by confidence band."""
    bands = {"50-60": 0, "60-70": 0, "70-80": 0, "80-90": 0, "90+": 0}
    for p in preds:
        c = p.get("confidence", 0) * 100
        if c >= 90:
            bands["90+"] += 1
        elif c >= 80:
            bands["80-90"] += 1
        elif c >= 70:
            bands["70-80"] += 1
        elif c >= 60:
            bands["60-70"] += 1
        else:
            bands["50-60"] += 1
    return bands


def sector_rotation(preds: list[dict]) -> dict:
    """Aggregate predictions by sector."""
    sector_data: dict[str, list] = defaultdict(list)
    for p in preds:
        symbol = p.get("symbol", "")
        sector = SECTOR_LOOKUP.get(symbol, p.get("sector", "Other"))
        sector_data[sector].append(p)

    result = {}
    for sector, items in sector_data.items():
        probs = [p.get("probability", 0.5) for p in items]
        avg_prob = sum(probs) / len(probs) if probs else 0.5
        sentiment = "bullish" if avg_prob > 0.55 else ("bearish" if avg_prob < 0.45 else "neutral")
        result[sector] = {
            "avgProbability": round(avg_prob, 4),
            "sentiment": sentiment,
            "tickerCount": len(items),
        }

    return dict(sorted(result.items()))


# ─── Main ──────────────────────────────────────────────────────

def generate_report() -> dict:
    now        = datetime.now(timezone.utc)
    week_label = iso_week_label(now)

    print(f"Generating weekly report for {week_label}…")

    preds   = load_predictions()
    entries = load_accuracy_log()
    meta    = load_model_metadata()

    print(f"  Loaded {len(preds)} predictions, {len(entries)} accuracy entries.")

    # Latest prediction per symbol
    latest: dict[str, dict] = {}
    for p in preds:
        sym = p.get("symbol", "")
        if not sym:
            continue
        existing = latest.get(sym)
        if existing is None or p.get("generatedAt", 0) > existing.get("generatedAt", 0):
            latest[sym] = p

    preds_list = list(latest.values())

    # Top bullish / bearish
    bullish = sorted(
        (p for p in preds_list if p.get("direction") == "UP"),
        key=lambda p: p.get("confidence", 0),
        reverse=True,
    )[:10]

    bearish = sorted(
        (p for p in preds_list if p.get("direction") == "DOWN"),
        key=lambda p: p.get("confidence", 0),
        reverse=True,
    )[:10]

    report = {
        "weekNumber":   week_label,
        "generatedAt":  now.isoformat().replace("+00:00", "Z"),
        "topBullish": [
            {
                "symbol":      p["symbol"],
                "probability": round(p.get("probability", 0.5), 4),
                "confidence":  round(p.get("confidence", 0.5), 4),
            }
            for p in bullish
        ],
        "topBearish": [
            {
                "symbol":      p["symbol"],
                "probability": round(p.get("probability", 0.5), 4),
                "confidence":  round(p.get("confidence", 0.5), 4),
            }
            for p in bearish
        ],
        "sectorRotation": sector_rotation(preds_list),
        "modelPerformance": {
            "rolling7d":  rolling_performance(entries, 7),
            "rolling30d": rolling_performance(entries, 30),
            "rolling90d": rolling_performance(entries, 90),
        },
        "confidenceDistribution": confidence_distribution(preds_list),
        "modelMetadata": {
            "version":      meta.get("version", "unknown"),
            "trainedAt":    meta.get("trainedAt", ""),
            "testAccuracy": meta.get("testAccuracy", None),
            # 32 features matches the V2 BiLSTM architecture (build-features.py)
            "features":     meta.get("features", 32),
        },
    }

    return report


def save_report(report: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{report['weekNumber']}.json"
    fpath = REPORTS_DIR / fname
    with open(fpath, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report saved to {fpath}")
    return fpath


if __name__ == "__main__":
    report = generate_report()
    save_report(report)
    print("Done.")
