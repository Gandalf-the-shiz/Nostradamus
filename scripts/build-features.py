"""
build-features.py — Phase 4: Server-Side Feature Engineering Pipeline

Reads raw OHLCV data from data/historical/*.json (Phase 3 output) and computes a
feature matrix per trading day per ticker using the `ta` library.

Phase A/B/C additions join sentiment, fundamental, and macro signals onto the
technical feature matrix, expanding FEATURE_COUNT from 33 to 40.

IMPORTANT — Feature Parity (Technical Note #11):
The browser-side preprocessing in js/ml/preprocessing.js must compute features
IDENTICALLY to this script. This server-side pipeline is the ground truth.
Phase 6 will update the browser-side code to match. Do NOT modify the feature
definitions here without also updating the Phase 6 backlog.

Output: data/features/<sector>.json (daily feature vectors, compact JSON)
        data/features/scaling_params.json (scaling metadata, indented JSON)
"""

import json
import os
import sys
import math
from datetime import datetime, timezone, date, timedelta

import numpy as np
import pandas as pd

# Technical Analysis library — provides RSI, MACD, Bollinger, ATR, OBV, Stochastic, ROC, SMA, EMA
import ta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HISTORICAL_DIR   = os.path.join(os.path.dirname(__file__), "..", "data", "historical")
FEATURES_DIR     = os.path.join(os.path.dirname(__file__), "..", "data", "features")
SENTIMENT_DIR    = os.path.join(os.path.dirname(__file__), "..", "data", "sentiment")
FUNDAMENTALS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "fundamentals")
MACRO_DIR        = os.path.join(os.path.dirname(__file__), "..", "data", "macro")

MIN_CANDLES  = 50          # skip tickers with fewer valid rows after indicator warmup
LOOKBACK_DAYS = 30        # window size (used in metadata; windowing done by Phase 5)
DECIMALS     = 4          # round all floats to 4 decimal places

# ---------------------------------------------------------------------------
# Feature schema — MUST stay in sync with generate-predictions.py
# ---------------------------------------------------------------------------

TECHNICAL_FEATURES = [
    "close_norm",       # 0
    "open_norm",        # 1
    "high_norm",        # 2
    "low_norm",         # 3
    "volume_norm",      # 4
    "rsi_14",           # 5
    "macd_line",        # 6
    "macd_signal",      # 7
    "macd_hist",        # 8
    "sma5_rel",         # 9
    "sma20_rel",        # 10
    "sma50_rel",        # 11
    "ema12_rel",        # 12
    "ema26_rel",        # 13
    "bb_upper_rel",     # 14
    "bb_lower_rel",     # 15
    "bb_width",         # 16
    "atr14_norm",       # 17
    "obv_norm",         # 18
    "stoch_k",          # 19
    "stoch_d",          # 20
    "roc10",            # 21
    "momentum5",        # 22
    "volatility30",     # 23
    "volume_ratio",     # 24
    "dow_mon",          # 25
    "dow_tue",          # 26
    "dow_wed",          # 27
    "dow_thu",          # 28
    "dow_fri",          # 29
    "month_sin",        # 30
    "month_cos",        # 31
    # Phase A: real NLP sentiment (replaces technical proxy)
    "news_sentiment",   # 32 — VADER compound score from NewsAPI headlines [-1,1]
    "reddit_sentiment", # 33 — VADER compound score from Reddit mentions [-1,1]
    "sec_filings_norm", # 34 — normalised 8-K filing count (past 7 days)
    # Phase B: fundamental signals
    "insider_buy_ratio",  # 35 — insider buy ratio past 30d [0,1], 0.5=neutral
    "earnings_days_norm", # 36 — days to next earnings normalised [0,1]
    "earnings_surprise",  # 37 — prior quarter EPS surprise, clipped [-0.5,0.5]
    "put_call_ratio_norm",# 38 — normalised put/call ratio [0,1]
    # Phase C: macro regime features
    "macro_vix_norm",     # 39 — normalised VIX [0,1]
]

FEATURE_NAMES = TECHNICAL_FEATURES
FEATURE_COUNT = len(FEATURE_NAMES)
assert FEATURE_COUNT == 40, f"FEATURE_NAMES length mismatch: {FEATURE_COUNT}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def minmax_scale(series: pd.Series) -> tuple[pd.Series, float, float]:
    """Min-max scale a Series to [0, 1]. Returns (scaled, min, max)."""
    mn = series.min()
    mx = series.max()
    rng = mx - mn
    if rng == 0:
        return pd.Series(0.5, index=series.index), float(mn), float(mx)
    return (series - mn) / rng, float(mn), float(mx)


def safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    """Element-wise division; returns 0 where b == 0."""
    return a.div(b.replace(0, np.nan)).fillna(0)


# ---------------------------------------------------------------------------
# Supplementary data loaders (Phase A/B/C)
# ---------------------------------------------------------------------------

def _load_latest_json(directory: str, file_pattern: str = "*.json") -> dict | None:
    """
    Load the most recent JSON file matching file_pattern from directory.
    Returns the parsed dict or None if no file found or on error.
    """
    import glob
    files = sorted(glob.glob(os.path.join(directory, file_pattern)))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            return json.load(f)
    except Exception as e:
        print(f"[build-features] WARN: could not load {files[-1]}: {e}")
        return None


def load_sentiment_data() -> dict[str, dict]:
    """
    Load the latest sentiment snapshot.
    Returns {ticker: {news_sentiment, reddit_sentiment, sec_filings_7d}} or {}.
    """
    data = _load_latest_json(SENTIMENT_DIR, "[0-9][0-9][0-9][0-9]-*.json")
    if data is None:
        print("[build-features] No sentiment data found — using zeros.")
        return {}
    tickers = data.get("tickers", {})
    print(f"[build-features] Loaded sentiment for {len(tickers)} tickers from {data.get('date')}")
    return tickers


def load_fundamentals_data() -> dict[str, dict]:
    """
    Load the latest fundamentals snapshot.
    Returns {ticker: {insider_buy_ratio_30d, earnings_days_to, earnings_surprise_prev,
                      put_call_ratio}} or {}.
    """
    data = _load_latest_json(FUNDAMENTALS_DIR, "[0-9][0-9][0-9][0-9]-*.json")
    if data is None:
        print("[build-features] No fundamentals data found — using defaults.")
        return {}
    tickers = data.get("tickers", {})
    print(f"[build-features] Loaded fundamentals for {len(tickers)} tickers from {data.get('date')}")
    return tickers


def load_macro_data() -> dict:
    """
    Load the latest macro snapshot (current-regime.json preferred, then latest dated file).
    Returns the macro dict or defaults.
    """
    # Try current-regime.json first
    regime_path = os.path.join(MACRO_DIR, "current-regime.json")
    if os.path.exists(regime_path):
        try:
            with open(regime_path) as f:
                data = json.load(f)
            print(f"[build-features] Loaded macro regime: {data.get('regime')} from {data.get('date')}")
            return data
        except Exception as e:
            print(f"[build-features] WARN: could not load current-regime.json: {e}")

    data = _load_latest_json(MACRO_DIR, "[0-9][0-9][0-9][0-9]-*.json")
    if data is None:
        print("[build-features] No macro data found — using defaults.")
        return {}
    return data


# ---------------------------------------------------------------------------
# Per-ticker feature computation
# ---------------------------------------------------------------------------

def compute_features(
    ticker: str,
    candles: list,
    sentiment_data: dict | None = None,
    fundamentals_data: dict | None = None,
    macro_features: dict | None = None,
) -> dict | None:
    """
    Given a list of OHLCV candle dicts, compute the full 40-feature matrix.

    Phases A/B/C signals are joined from the supplementary data dicts:
      sentiment_data    — {ticker: {news_sentiment, reddit_sentiment, sec_filings_7d}}
      fundamentals_data — {ticker: {insider_buy_ratio_30d, earnings_days_to,
                                    earnings_surprise_prev, put_call_ratio}}
      macro_features    — {macro_vix_norm, macro_spread_norm, ...}

    These external signals are applied to the *most recent* rows of the feature
    matrix only (since they represent today's snapshot). Historical rows use the
    technical proxy for the sentiment slot to maintain training continuity.

    Returns a dict with keys: dates, features, labels, scaling_params
    or None if the ticker has insufficient data.
    """
    if len(candles) < MIN_CANDLES:
        return None

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    # --- Min-max scale price/volume columns ---
    close_norm, price_min, price_max = minmax_scale(close)
    open_norm, _, _ = minmax_scale(open_)
    high_norm, _, _ = minmax_scale(high)
    low_norm, _, _ = minmax_scale(low)
    volume_norm, vol_min, vol_max = minmax_scale(volume)

    # --- RSI-14 ---
    rsi_14 = ta.momentum.RSIIndicator(close=close, window=14).rsi() / 100.0

    # --- MACD ---
    macd_obj = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line = safe_div(macd_obj.macd(), close)
    macd_signal = safe_div(macd_obj.macd_signal(), close)
    macd_hist = safe_div(macd_obj.macd_diff(), close)

    # --- SMAs (relative to close) ---
    sma5 = ta.trend.SMAIndicator(close=close, window=5).sma_indicator()
    sma20 = ta.trend.SMAIndicator(close=close, window=20).sma_indicator()
    sma50 = ta.trend.SMAIndicator(close=close, window=50).sma_indicator()
    sma5_rel = safe_div(sma5 - close, close)
    sma20_rel = safe_div(sma20 - close, close)
    sma50_rel = safe_div(sma50 - close, close)

    # --- EMAs (relative to close) ---
    ema12 = ta.trend.EMAIndicator(close=close, window=12).ema_indicator()
    ema26 = ta.trend.EMAIndicator(close=close, window=26).ema_indicator()
    ema12_rel = safe_div(ema12 - close, close)
    ema26_rel = safe_div(ema26 - close, close)

    # --- Bollinger Bands ---
    bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    bb_upper = bb.bollinger_hband()
    bb_lower = bb.bollinger_lband()
    bb_upper_rel = safe_div(bb_upper - close, close)
    bb_lower_rel = safe_div(close - bb_lower, close)
    bb_width = safe_div(bb_upper - bb_lower, close)

    # --- ATR-14 ---
    atr14 = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
    atr14_norm = safe_div(atr14, close)

    # --- OBV ---
    obv_raw = ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    obv_norm, obv_min, obv_max = minmax_scale(obv_raw)

    # --- Stochastic Oscillator ---
    stoch = ta.momentum.StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    stoch_k = stoch.stoch() / 100.0
    stoch_d = stoch.stoch_signal() / 100.0

    # --- ROC-10 ---
    roc10 = ta.momentum.ROCIndicator(close=close, window=10).roc() / 100.0

    # --- 5-day price momentum (manual) ---
    close_5d_ago = close.shift(5)
    momentum5 = safe_div(close - close_5d_ago, close_5d_ago)

    # --- 30-day realized volatility (manual, annualized) ---
    daily_returns = close.pct_change()
    volatility30 = daily_returns.rolling(30).std() * math.sqrt(252)

    # --- Volume ratio (manual) ---
    vol_sma20 = volume.rolling(20).mean()
    volume_ratio = safe_div(volume, vol_sma20)

    # --- Calendar features ---
    dow = df["date"].dt.dayofweek   # Monday=0, Friday=4
    dow_mon = (dow == 0).astype(float)
    dow_tue = (dow == 1).astype(float)
    dow_wed = (dow == 2).astype(float)
    dow_thu = (dow == 3).astype(float)
    dow_fri = (dow == 4).astype(float)

    month = df["date"].dt.month
    month_sin = np.sin(2 * math.pi * month / 12)
    month_cos = np.cos(2 * math.pi * month / 12)

    # -------------------------------------------------------------------------
    # Phase A: Real sentiment features
    # For historical rows we use a technical proxy (same formula as before).
    # The most recent row (today's snapshot) is overwritten with real NLP scores
    # when sentiment_data is available.
    # -------------------------------------------------------------------------

    n_rows = len(df)

    # Technical proxy (used for all rows as fallback)
    rsi_deviation  = (rsi_14 - 0.5) * 2
    sentiment_proxy = (rsi_deviation * 0.5 + momentum5 * 2 + macd_hist * 10).apply(math.tanh)

    news_sentiment_series   = pd.Series(0.0, index=df.index)
    reddit_sentiment_series = pd.Series(0.0, index=df.index)
    sec_filings_series      = pd.Series(0.0, index=df.index)

    # Override the last row with real sentiment when available
    if sentiment_data and ticker in sentiment_data:
        sd = sentiment_data[ticker]
        last_idx = n_rows - 1
        news_sentiment_series.iloc[last_idx]   = float(sd.get("news_sentiment",   0.0) or 0.0)
        reddit_sentiment_series.iloc[last_idx] = float(sd.get("reddit_sentiment", 0.0) or 0.0)
        # Normalise sec_filings_7d: clamp [0, 10] → [0, 1]
        raw_filings = float(sd.get("sec_filings_7d", 0) or 0)
        sec_filings_series.iloc[last_idx] = min(1.0, raw_filings / 10.0)

    # For older rows, fill news_sentiment with the technical proxy so the model
    # sees a smooth signal throughout training. Note: zero is treated as "no signal
    # (neutral)" here, not as genuine zero sentiment — the VADER compound score
    # would rarely be exactly 0.0, so this distinguishes missing from actual data.
    news_sentiment_series = news_sentiment_series.where(
        news_sentiment_series != 0.0, other=sentiment_proxy
    )

    # -------------------------------------------------------------------------
    # Phase B: Fundamental features (static snapshot applied to all rows)
    # -------------------------------------------------------------------------

    insider_buy_ratio   = pd.Series(0.5,  index=df.index)  # neutral default
    earnings_days_norm  = pd.Series(1.0,  index=df.index)  # far from earnings
    earnings_surprise   = pd.Series(0.0,  index=df.index)  # no surprise
    put_call_ratio_norm = pd.Series(0.5,  index=df.index)  # neutral

    if fundamentals_data and ticker in fundamentals_data:
        fd = fundamentals_data[ticker]
        # insider_buy_ratio_30d is already [0,1]
        ibr = float(fd.get("insider_buy_ratio_30d", 0.5) or 0.5)
        insider_buy_ratio.iloc[:] = max(0.0, min(1.0, ibr))

        # earnings_days_to: normalise [0,60] → [0,1], inverted (0 = earnings very soon)
        edd = float(fd.get("earnings_days_to", 60) or 60)
        earnings_days_norm.iloc[:] = max(0.0, min(1.0, 1.0 - edd / 60.0))

        # earnings_surprise_prev: already clipped to [-0.5, 0.5]
        esp = float(fd.get("earnings_surprise_prev", 0.0) or 0.0)
        earnings_surprise.iloc[:] = max(-0.5, min(0.5, esp))

        # put_call_ratio: normalise [0, 5] → [0, 1]
        pcr = float(fd.get("put_call_ratio", 1.0) or 1.0)
        put_call_ratio_norm.iloc[:] = max(0.0, min(1.0, pcr / 5.0))

    # -------------------------------------------------------------------------
    # Phase C: Macro regime features (scalar from current-regime.json)
    # -------------------------------------------------------------------------

    macro_vix_norm_val = 0.3  # moderate VIX default
    if macro_features:
        macro_vix_norm_val = float(macro_features.get("macro_vix_norm", 0.3) or 0.3)
    macro_vix_norm_series = pd.Series(macro_vix_norm_val, index=df.index)

    # --- Assemble feature matrix ---
    feature_df = pd.DataFrame({
        "close_norm":         close_norm,
        "open_norm":          open_norm,
        "high_norm":          high_norm,
        "low_norm":           low_norm,
        "volume_norm":        volume_norm,
        "rsi_14":             rsi_14,
        "macd_line":          macd_line,
        "macd_signal":        macd_signal,
        "macd_hist":          macd_hist,
        "sma5_rel":           sma5_rel,
        "sma20_rel":          sma20_rel,
        "sma50_rel":          sma50_rel,
        "ema12_rel":          ema12_rel,
        "ema26_rel":          ema26_rel,
        "bb_upper_rel":       bb_upper_rel,
        "bb_lower_rel":       bb_lower_rel,
        "bb_width":           bb_width,
        "atr14_norm":         atr14_norm,
        "obv_norm":           obv_norm,
        "stoch_k":            stoch_k,
        "stoch_d":            stoch_d,
        "roc10":              roc10,
        "momentum5":          momentum5,
        "volatility30":       volatility30,
        "volume_ratio":       volume_ratio,
        "dow_mon":            dow_mon,
        "dow_tue":            dow_tue,
        "dow_wed":            dow_wed,
        "dow_thu":            dow_thu,
        "dow_fri":            dow_fri,
        "month_sin":          month_sin,
        "month_cos":          month_cos,
        # Phase A
        "news_sentiment":     news_sentiment_series,
        "reddit_sentiment":   reddit_sentiment_series,
        "sec_filings_norm":   sec_filings_series,
        # Phase B
        "insider_buy_ratio":  insider_buy_ratio,
        "earnings_days_norm": earnings_days_norm,
        "earnings_surprise":  earnings_surprise,
        "put_call_ratio_norm": put_call_ratio_norm,
        # Phase C
        "macro_vix_norm":     macro_vix_norm_series,
    })

    # --- Labels: did price go UP the next day? ---
    next_close = close.shift(-1)
    label = (next_close > close).astype(int)

    # --- Regression target: next-day percentage return, clipped to ±20% ---
    pct_return = ((next_close - close) / close).clip(-0.20, 0.20)

    # Drop rows with NaN in any feature (indicator warmup period) and the last row
    # (whose label is NaN because next_close is undefined for the final candle).
    # Both cases are handled by dropna() since label NaN propagates into _label.
    feature_df["_label"] = label
    feature_df["_pct_return"] = pct_return
    feature_df["_date"] = df["date"].dt.strftime("%Y-%m-%d")
    feature_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    feature_df.dropna(inplace=True)

    if len(feature_df) < MIN_CANDLES:
        return None

    dates = feature_df["_date"].tolist()
    labels = feature_df["_label"].astype(int).tolist()
    pct_returns = [round(float(v), DECIMALS) for v in feature_df["_pct_return"].tolist()]
    raw_features = feature_df[FEATURE_NAMES].values

    # Round to 4 decimal places
    features_rounded = [[round(float(v), DECIMALS) for v in row] for row in raw_features]

    return {
        "dates": dates,
        "features": features_rounded,
        "labels": labels,
        "pct_returns": pct_returns,
        "scaling_params": {
            "priceMin": round(price_min, DECIMALS),
            "priceMax": round(price_max, DECIMALS),
            "volumeMin": round(vol_min, DECIMALS),
            "volumeMax": round(vol_max, DECIMALS),
            "obvMin": round(obv_min, DECIMALS),
            "obvMax": round(obv_max, DECIMALS),
        },
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_sector(sector_file: str, sector_name: str,
                   sentiment_data: dict | None = None,
                   fundamentals_data: dict | None = None,
                   macro_features: dict | None = None) -> dict:
    """Process one sector JSON file. Returns sector output dict + stats."""
    print(f"[build-features] Loading {sector_name}...")

    with open(sector_file, "r") as f:
        sector_data = json.load(f)

    stocks = sector_data.get("stocks", {})
    total_tickers = len(stocks)

    tickers_out = {}
    per_ticker_scaling = {}
    total_days = 0
    total_up = 0
    total_down = 0
    skipped = 0
    processed = 0

    for i, (ticker, stock_info) in enumerate(stocks.items(), 1):
        if i % 50 == 0 or i == total_tickers:
            print(f"[build-features] Processing {sector_name}: {i}/{total_tickers} tickers...")

        candles = stock_info.get("candles", [])
        result = compute_features(ticker, candles,
                                   sentiment_data=sentiment_data,
                                   fundamentals_data=fundamentals_data,
                                   macro_features=macro_features)

        if result is None:
            skipped += 1
            continue

        processed += 1
        n = len(result["dates"])
        total_days += n
        total_up += sum(result["labels"])
        total_down += (n - sum(result["labels"]))

        per_ticker_scaling[ticker] = result["scaling_params"]

        tickers_out[ticker] = {
            "days": n,
            "dates": result["dates"],
            "features": result["features"],
            "labels": result["labels"],
            "pct_returns": result["pct_returns"],
        }

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "sector": sector_data.get("sector", sector_name),
        "featureCount": FEATURE_COUNT,
        "featureNames": FEATURE_NAMES,
        "lookbackDays": LOOKBACK_DAYS,
        "lastBuilt": now,
        "tickerCount": processed,
        "totalDays": total_days,
        "tickers": tickers_out,
    }

    print(
        f"[build-features] {sector_name}: {processed} processed, "
        f"{skipped} skipped, {total_days} feature-days"
    )

    return {
        "output": output,
        "per_ticker_scaling": per_ticker_scaling,
        "processed": processed,
        "skipped": skipped,
        "total_days": total_days,
        "total_up": total_up,
        "total_down": total_down,
        "sector_name": sector_data.get("sector", sector_name),
    }


def main():
    os.makedirs(FEATURES_DIR, exist_ok=True)

    # Load manifest to understand available sectors
    manifest_path = os.path.join(HISTORICAL_DIR, "manifest.json")
    if not os.path.exists(manifest_path):
        print("[build-features] ERROR: data/historical/manifest.json not found. Run fetch-history.py first.")
        sys.exit(1)

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    sectors_in_manifest = manifest.get("sectorFiles", {})
    print(f"[build-features] Found {len(sectors_in_manifest)} sectors in manifest.")

    # --- Load supplementary data (Phase A/B/C) ---
    sentiment_data    = load_sentiment_data()
    fundamentals_data = load_fundamentals_data()
    macro_data        = load_macro_data()
    macro_features    = macro_data.get("normalisedFeatures") if macro_data else None
    if macro_features:
        print(f"[build-features] Macro regime: {macro_data.get('regime')} | VIX norm: {macro_features.get('macro_vix_norm')}")

    # Discover sector files
    sector_files = []
    for entry in os.listdir(HISTORICAL_DIR):
        if entry.endswith(".json") and entry != "manifest.json":
            sector_files.append(os.path.join(HISTORICAL_DIR, entry))

    if not sector_files:
        print("[build-features] ERROR: No sector files found in data/historical/. Run fetch-history.py first.")
        sys.exit(1)

    print(f"[build-features] Processing {len(sector_files)} sector files...")

    # Aggregate stats
    all_per_ticker_scaling = {}
    all_sectors_processed = []
    global_processed = 0
    global_skipped = 0
    global_days = 0
    global_up = 0
    global_down = 0

    for sector_file in sorted(sector_files):
        sector_name = os.path.basename(sector_file).replace(".json", "")
        result = process_sector(
            sector_file, sector_name,
            sentiment_data=sentiment_data,
            fundamentals_data=fundamentals_data,
            macro_features=macro_features,
        )

        # Write compact sector feature file
        out_path = os.path.join(FEATURES_DIR, os.path.basename(sector_file))
        with open(out_path, "w") as f:
            json.dump(result["output"], f, separators=(",", ":"))
        print(f"[build-features] Wrote {out_path}")

        all_per_ticker_scaling.update(result["per_ticker_scaling"])
        all_sectors_processed.append(result["sector_name"])
        global_processed += result["processed"]
        global_skipped += result["skipped"]
        global_days += result["total_days"]
        global_up += result["total_up"]
        global_down += result["total_down"]

    total_samples = global_up + global_down
    up_ratio = round(global_up / total_samples, 4) if total_samples > 0 else 0.0

    scaling_params = {
        "featureCount": FEATURE_COUNT,
        "featureNames": FEATURE_NAMES,
        "lookbackDays": LOOKBACK_DAYS,
        "perTickerScaling": all_per_ticker_scaling,
        "globalStats": {
            "totalSamples": total_samples,
            "upSamples": global_up,
            "downSamples": global_down,
            "upRatio": up_ratio,
            "sectorsProcessed": all_sectors_processed,
            "tickersProcessed": global_processed,
            "tickersSkipped": global_skipped,
        },
    }

    scaling_path = os.path.join(FEATURES_DIR, "scaling_params.json")
    with open(scaling_path, "w") as f:
        json.dump(scaling_params, f, indent=2)
    print(f"[build-features] Wrote {scaling_path}")

    # Summary
    print()
    print("=" * 60)
    print("[build-features] DONE")
    print(f"  Sectors processed : {len(all_sectors_processed)}")
    print(f"  Tickers processed : {global_processed}")
    print(f"  Tickers skipped   : {global_skipped}")
    print(f"  Total feature-days: {global_days}")
    print(f"  Total samples     : {total_samples}")
    print(f"  UP / DOWN ratio   : {global_up} / {global_down} ({up_ratio:.1%} up)")
    print(f"  Feature count     : {FEATURE_COUNT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
