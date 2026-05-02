"""
fetch-macro.py — Phase C: Macroeconomic Regime Data via FRED API

Fetches key macroeconomic time series from the Federal Reserve Economic Data (FRED)
API and writes a snapshot to data/macro/YYYY-MM-DD.json.

Series fetched:
  DFF     — Fed Funds Rate (daily)
  T10Y2Y  — 10Y-2Y Treasury yield spread (yield curve)
  VIXCLS  — CBOE Volatility Index (VIX)
  UMCSENT — University of Michigan Consumer Sentiment
  ICSA    — Initial Jobless Claims (weekly)
  SP500   — S&P 500 Price Index (monthly)
  M2SL    — M2 Money Supply (monthly)

Output: data/macro/YYYY-MM-DD.json
  {
    "date": "YYYY-MM-DD",
    "generatedAt": "...",
    "series": {
      "DFF": 5.33,
      "T10Y2Y": -0.22,
      "VIXCLS": 18.4,
      "UMCSENT": 67.8,
      "ICSA": 220000,
      "SP500": 5100.0,
      "M2SL": 20900.0
    },
    "regime": "BULL"  | "BEAR" | "HIGH_VOL" | "SIDEWAYS"
  }

FRED API key: free at https://fred.stlouisfed.org/docs/api/api_key.html
Set as FRED_API_KEY GitHub secret.

Run weekly via .github/workflows/fetch-macro.yml.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent
MACRO_DIR  = REPO_ROOT / "data" / "macro"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
FRED_BASE    = "https://api.stlouisfed.org/fred/series/observations"

# Which FRED series to pull and their default values when unavailable
FRED_SERIES = {
    "DFF":     {"description": "Fed Funds Rate (%)",        "default": 5.0},
    "T10Y2Y":  {"description": "10Y-2Y Yield Spread (%)",   "default": 0.0},
    "VIXCLS":  {"description": "VIX Volatility Index",      "default": 20.0},
    "UMCSENT": {"description": "Consumer Sentiment Index",  "default": 70.0},
    "ICSA":    {"description": "Initial Jobless Claims",    "default": 230000.0},
    "SP500":   {"description": "S&P 500 Price Index",       "default": 4500.0},
    "M2SL":    {"description": "M2 Money Supply (B$)",      "default": 20000.0},
}

# Regime thresholds (tuned to empirical historical distributions)
VIX_HIGH_THRESHOLD  = 25.0    # VIX > 25 → HIGH_VOL
VIX_BEAR_THRESHOLD  = 18.0    # VIX > this while yield curve inverted → BEAR
SPREAD_BEAR_THRESH  = -0.30   # Inverted yield curve below -0.30% → BEAR signal
SPREAD_BULL_THRESH  =  0.50   # Positive spread > 0.50% → BULL signal


# ---------------------------------------------------------------------------
# FRED data fetch
# ---------------------------------------------------------------------------

def fetch_fred_series(series_id: str, lookback_days: int = 90) -> float | None:
    """
    Fetch the most recent non-null value for a FRED series.
    Returns the float value or None on failure.
    """
    if not FRED_API_KEY:
        return None

    try:
        import requests
    except ImportError:
        return None

    observation_start = (date.today() - timedelta(days=lookback_days)).isoformat()

    try:
        resp = requests.get(
            FRED_BASE,
            params={
                "series_id":         series_id,
                "api_key":           FRED_API_KEY,
                "file_type":         "json",
                "observation_start": observation_start,
                "sort_order":        "desc",
                "limit":             10,
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])

        for obs in observations:
            val_str = obs.get("value", ".")
            if val_str != ".":
                return float(val_str)

        return None

    except Exception as e:
        print(f"[fetch-macro] FRED error ({series_id}): {e}")
        return None


def fetch_all_series() -> dict[str, float]:
    """Fetch all configured FRED series. Falls back to defaults on failure."""
    values: dict[str, float] = {}

    if not FRED_API_KEY:
        print("[fetch-macro] FRED_API_KEY not set — using default macro values.")
        for sid, cfg in FRED_SERIES.items():
            values[sid] = cfg["default"]
        return values

    for series_id, cfg in FRED_SERIES.items():
        val = fetch_fred_series(series_id)
        if val is None:
            print(f"[fetch-macro] {series_id}: no data — using default {cfg['default']}")
            val = cfg["default"]
        else:
            print(f"[fetch-macro] {series_id}: {val}")
        values[series_id] = round(val, 4)
        time.sleep(0.2)   # be polite to FRED API

    return values


# ---------------------------------------------------------------------------
# Regime detection (rule-based, deterministic)
# ---------------------------------------------------------------------------

def classify_regime(series: dict[str, float]) -> str:
    """
    Classify the current macro regime from FRED data.
    Returns one of: "BULL", "BEAR", "HIGH_VOL", "SIDEWAYS"

    Rules (applied in priority order):
    1. HIGH_VOL: VIX > 25
    2. BEAR:     Yield curve deeply inverted (T10Y2Y < -0.30) AND VIX elevated
    3. BULL:     Yield curve positive (T10Y2Y > 0.50) AND VIX moderate (<20)
    4. SIDEWAYS: Everything else
    """
    vix     = series.get("VIXCLS",  FRED_SERIES["VIXCLS"]["default"])
    spread  = series.get("T10Y2Y",  FRED_SERIES["T10Y2Y"]["default"])
    fed_rate = series.get("DFF",     FRED_SERIES["DFF"]["default"])
    claims  = series.get("ICSA",    FRED_SERIES["ICSA"]["default"])

    # HIGH_VOL regime: fear spike
    if vix > VIX_HIGH_THRESHOLD:
        return "HIGH_VOL"

    # BEAR regime: inverted yield curve + elevated stress
    if spread < SPREAD_BEAR_THRESH and vix > VIX_BEAR_THRESHOLD:
        return "BEAR"

    # BULL regime: positive yield curve + low volatility
    if spread > SPREAD_BULL_THRESH and vix < 20.0:
        return "BULL"

    return "SIDEWAYS"


# ---------------------------------------------------------------------------
# Normalised macro feature vector (for injection into model features)
# ---------------------------------------------------------------------------

def compute_normalised_features(series: dict[str, float]) -> dict[str, float]:
    """
    Convert raw FRED values into normalised features suitable for model input.
    All outputs are clipped to a reasonable range and scaled to roughly [0, 1].
    """
    # VIX: normalise [10, 80] → [0, 1]
    vix_norm = max(0.0, min(1.0, (series.get("VIXCLS", 20.0) - 10.0) / 70.0))

    # Yield spread: normalise [-2, 2] → [0, 1]
    spread_norm = max(0.0, min(1.0, (series.get("T10Y2Y", 0.0) + 2.0) / 4.0))

    # Fed rate: normalise [0, 10] → [0, 1]
    fed_norm = max(0.0, min(1.0, series.get("DFF", 5.0) / 10.0))

    # Consumer sentiment: normalise [50, 110] → [0, 1]
    sentiment_norm = max(0.0, min(1.0, (series.get("UMCSENT", 70.0) - 50.0) / 60.0))

    # Initial claims: normalise [150k, 600k] → [0, 1], inverted (high claims = bad)
    claims_norm = max(0.0, min(1.0, 1.0 - (series.get("ICSA", 230000.0) - 150000.0) / 450000.0))

    return {
        "macro_vix_norm":      round(vix_norm, 4),
        "macro_spread_norm":   round(spread_norm, 4),
        "macro_fed_norm":      round(fed_norm, 4),
        "macro_sentiment_norm": round(sentiment_norm, 4),
        "macro_claims_norm":   round(claims_norm, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    MACRO_DIR.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    out_path  = MACRO_DIR / f"{today_str}.json"
    regime_path = MACRO_DIR / "current-regime.json"

    print("=" * 60)
    print(f"[fetch-macro] Fetching macroeconomic data for {today_str}")
    print("=" * 60)

    # Fetch all FRED series
    series = fetch_all_series()

    # Classify regime
    regime = classify_regime(series)
    print(f"\n[fetch-macro] Regime classification: {regime}")

    # Compute normalised features
    norm_features = compute_normalised_features(series)
    print(f"[fetch-macro] Normalised macro features: {norm_features}")

    # Build output
    output = {
        "date":              today_str,
        "generatedAt":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fredApiAvailable":  bool(FRED_API_KEY),
        "series":            series,
        "regime":            regime,
        "normalisedFeatures": norm_features,
    }

    # Write dated snapshot
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[fetch-macro] Wrote snapshot: {out_path}")

    # Overwrite current-regime.json (always points to the latest)
    with open(regime_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[fetch-macro] Updated current regime: {regime_path}")

    print()
    print("=" * 60)
    print(f"[fetch-macro] DONE — Regime: {regime}")
    print("=" * 60)


if __name__ == "__main__":
    main()
