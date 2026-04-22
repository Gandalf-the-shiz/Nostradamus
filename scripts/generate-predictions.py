"""
generate-predictions.py — Daily Prediction Generation

Loads the trained V2 model from models/v2/ and the latest historical data
from data/historical/, computes features using the same pipeline as
build-features.py, and generates UP/DOWN predictions for all tickers.

Output: data/predictions/YYYY-MM-DD.json

Run daily after market close (see .github/workflows/generate-predictions.yml).
"""

import json
import math
import os
import sys
from datetime import datetime, timezone, date, timedelta

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT       = os.path.join(SCRIPT_DIR, "..")
HISTORICAL_DIR  = os.path.join(REPO_ROOT, "data", "historical")
FEATURES_DIR    = os.path.join(REPO_ROOT, "data", "features")
MODELS_V2_DIR   = os.path.join(REPO_ROOT, "models", "v2")
PREDICTIONS_DIR = os.path.join(REPO_ROOT, "data", "predictions")

# ---------------------------------------------------------------------------
# Constants (must match build-features.py and train-model.py)
# ---------------------------------------------------------------------------

TIMESTEPS     = 30
FEATURE_COUNT = 33
MIN_CANDLES   = 60   # minimum candles needed after indicator warmup

FEATURE_NAMES = [
    "close_norm", "open_norm", "high_norm", "low_norm", "volume_norm",
    "rsi_14", "macd_line", "macd_signal", "macd_hist",
    "sma5_rel", "sma20_rel", "sma50_rel",
    "ema12_rel", "ema26_rel",
    "bb_upper_rel", "bb_lower_rel", "bb_width",
    "atr14_norm", "obv_norm",
    "stoch_k", "stoch_d",
    "roc10", "momentum5", "volatility30", "volume_ratio",
    "dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri",
    "month_sin", "month_cos",
    "sentiment",
]
assert len(FEATURE_NAMES) == FEATURE_COUNT

# ---------------------------------------------------------------------------
# Re-use feature computation from build-features.py
# ---------------------------------------------------------------------------

def _build_features_for_candles(candles: list) -> list[list[float]] | None:
    """
    Compute the 33-feature matrix for a list of OHLCV candle dicts.
    Returns a list of feature rows (each a list of 33 floats), or None if
    there isn't enough data.

    This function mirrors the logic in build-features.py so that
    browser-side inference and server-side scoring stay in sync.
    """
    try:
        import ta
        import pandas as pd
    except ImportError:
        print("ERROR: 'ta' and 'pandas' packages required. Run: pip install ta pandas")
        sys.exit(1)

    if len(candles) < MIN_CANDLES:
        return None

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    close   = df["close"].astype(float)
    open_   = df["open"].astype(float)
    high    = df["high"].astype(float)
    low     = df["low"].astype(float)
    volume  = df["volume"].astype(float)

    def minmax(s):
        mn, mx = s.min(), s.max()
        rng = mx - mn
        return ((s - mn) / rng) if rng != 0 else pd.Series(0.5, index=s.index)

    def safe_div(a, b):
        return a.div(b.replace(0, float("nan"))).fillna(0)

    close_norm  = minmax(close)
    open_norm   = minmax(open_)
    high_norm   = minmax(high)
    low_norm    = minmax(low)
    volume_norm = minmax(volume)

    rsi_14   = ta.momentum.RSIIndicator(close=close, window=14).rsi() / 100.0
    macd_obj = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line   = safe_div(macd_obj.macd(), close)
    macd_signal = safe_div(macd_obj.macd_signal(), close)
    macd_hist   = safe_div(macd_obj.macd_diff(), close)

    sma5  = ta.trend.SMAIndicator(close=close, window=5).sma_indicator()
    sma20 = ta.trend.SMAIndicator(close=close, window=20).sma_indicator()
    sma50 = ta.trend.SMAIndicator(close=close, window=50).sma_indicator()
    sma5_rel  = safe_div(sma5  - close, close)
    sma20_rel = safe_div(sma20 - close, close)
    sma50_rel = safe_div(sma50 - close, close)

    ema12 = ta.trend.EMAIndicator(close=close, window=12).ema_indicator()
    ema26 = ta.trend.EMAIndicator(close=close, window=26).ema_indicator()
    ema12_rel = safe_div(ema12 - close, close)
    ema26_rel = safe_div(ema26 - close, close)

    bb         = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    bb_upper_rel = safe_div(bb.bollinger_hband() - close, close)
    bb_lower_rel = safe_div(close - bb.bollinger_lband(), close)
    bb_width     = safe_div(bb.bollinger_hband() - bb.bollinger_lband(), close)

    atr14_norm = safe_div(
        ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range(),
        close
    )

    obv_raw = ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    obv_min, obv_max = obv_raw.min(), obv_raw.max()
    obv_norm = ((obv_raw - obv_min) / (obv_max - obv_min)) if obv_max != obv_min else pd.Series(0.5, index=obv_raw.index)

    stoch = ta.momentum.StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    stoch_k = stoch.stoch() / 100.0
    stoch_d = stoch.stoch_signal() / 100.0

    roc10     = ta.momentum.ROCIndicator(close=close, window=10).roc() / 100.0
    momentum5 = safe_div(close - close.shift(5), close.shift(5))

    daily_returns = close.pct_change()
    volatility30  = daily_returns.rolling(30).std() * math.sqrt(252)

    vol_sma20     = volume.rolling(20).mean()
    volume_ratio  = safe_div(volume, vol_sma20)

    dow       = df["date"].dt.dayofweek
    dow_mon   = (dow == 0).astype(float)
    dow_tue   = (dow == 1).astype(float)
    dow_wed   = (dow == 2).astype(float)
    dow_thu   = (dow == 3).astype(float)
    dow_fri   = (dow == 4).astype(float)

    month     = df["date"].dt.month
    month_sin = np.sin(2 * math.pi * month / 12)
    month_cos = np.cos(2 * math.pi * month / 12)

    # --- Sentiment proxy (technical composite, matching build-features.py) ---
    rsi_deviation = (rsi_14 - 0.5) * 2
    sentiment_proxy = (rsi_deviation * 0.5 + momentum5 * 2 + macd_hist * 10).apply(math.tanh)

    feature_df = pd.DataFrame({
        "close_norm":   close_norm, "open_norm":    open_norm,
        "high_norm":    high_norm,  "low_norm":     low_norm,
        "volume_norm":  volume_norm,"rsi_14":       rsi_14,
        "macd_line":    macd_line,  "macd_signal":  macd_signal,
        "macd_hist":    macd_hist,  "sma5_rel":     sma5_rel,
        "sma20_rel":    sma20_rel,  "sma50_rel":    sma50_rel,
        "ema12_rel":    ema12_rel,  "ema26_rel":    ema26_rel,
        "bb_upper_rel": bb_upper_rel,"bb_lower_rel": bb_lower_rel,
        "bb_width":     bb_width,   "atr14_norm":   atr14_norm,
        "obv_norm":     obv_norm,   "stoch_k":      stoch_k,
        "stoch_d":      stoch_d,    "roc10":        roc10,
        "momentum5":    momentum5,  "volatility30": volatility30,
        "volume_ratio": volume_ratio,
        "dow_mon":      dow_mon,    "dow_tue":      dow_tue,
        "dow_wed":      dow_wed,    "dow_thu":      dow_thu,
        "dow_fri":      dow_fri,    "month_sin":    month_sin,
        "month_cos":    month_cos,
        "sentiment":    sentiment_proxy,
    })

    import numpy as _np
    feature_df.replace([_np.inf, -_np.inf], _np.nan, inplace=True)
    feature_df.dropna(inplace=True)

    if len(feature_df) < TIMESTEPS:
        return None

    return feature_df[FEATURE_NAMES].values.tolist()


# ---------------------------------------------------------------------------
# Model loading and inference
# ---------------------------------------------------------------------------

def load_model():
    """Load the V2 TensorFlow model for server-side inference."""
    model_path = os.path.join(MODELS_V2_DIR, "saved_model")
    keras_path = os.path.join(MODELS_V2_DIR, "keras_model.keras")
    h5_path    = os.path.join(MODELS_V2_DIR, "model.h5")

    for path in [keras_path, h5_path, model_path]:
        if os.path.exists(path):
            try:
                import tensorflow as tf
                model = tf.keras.models.load_model(path)
                print(f"[generate-predictions] Loaded model from {path}")
                return model
            except Exception as e:
                print(f"[generate-predictions] Could not load {path}: {e}")

    print("[generate-predictions] ERROR: No trained V2 model found in models/v2/")
    print("  Run scripts/train-model.py first.")
    sys.exit(1)


def predict_ticker(model, features: list[list[float]]) -> dict:
    """
    Run inference on the last TIMESTEPS rows of a feature matrix.
    Returns probability, direction, confidence, and predictedReturn when available.

    Handles both single-head (legacy) and dual-head models:
    - Single-head: outputs P(UP) as a scalar
    - Dual-head: outputs [cls_output, reg_output] — P(UP) and predicted % return
    """
    import numpy as np

    window = np.array([features[-TIMESTEPS:]], dtype=np.float32)  # shape (1, 30, 33)
    outputs = model.predict(window, verbose=0)

    # Handle dual-head vs single-head output
    if isinstance(outputs, list) and len(outputs) == 2:
        probability = float(outputs[0][0][0])
        predicted_return = float(outputs[1][0][0])
    else:
        probability = float(outputs[0][0])
        predicted_return = None

    direction   = "UP" if probability > 0.5 else "DOWN"
    confidence  = round(abs(probability - 0.5) * 2, 4)

    result = {
        "probability": round(probability, 4),
        "direction":   direction,
        "confidence":  confidence,
    }
    if predicted_return is not None:
        result["predictedReturn"] = round(predicted_return, 4)
    return result


# ---------------------------------------------------------------------------
# Historical data loading
# ---------------------------------------------------------------------------

def load_historical_candles(sector_file: str) -> dict[str, list]:
    """Load candles for every ticker in a sector JSON file."""
    with open(sector_file) as f:
        data = json.load(f)
    result = {}
    for ticker, info in data.get("stocks", {}).items():
        candles = info.get("candles", [])
        if candles:
            result[ticker] = candles
    return result


# ---------------------------------------------------------------------------
# Next trading day helper
# ---------------------------------------------------------------------------

def next_trading_day(from_date: date) -> str:
    """Return the next weekday after from_date as YYYY-MM-DD."""
    d = from_date + timedelta(days=1)
    while d.weekday() >= 5:   # 5=Sat, 6=Sun
        d += timedelta(days=1)
    return d.isoformat()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)

    today_str = date.today().isoformat()
    prediction_date = next_trading_day(date.today())

    out_path = os.path.join(PREDICTIONS_DIR, f"{today_str}.json")

    # Load model
    model = load_model()

    # Load manifest to find sector files
    manifest_path = os.path.join(HISTORICAL_DIR, "manifest.json")
    if not os.path.exists(manifest_path):
        print("[generate-predictions] ERROR: data/historical/manifest.json not found.")
        sys.exit(1)

    sector_files = [
        os.path.join(HISTORICAL_DIR, f)
        for f in os.listdir(HISTORICAL_DIR)
        if f.endswith(".json") and f != "manifest.json"
    ]

    if not sector_files:
        print("[generate-predictions] ERROR: No sector files found in data/historical/")
        sys.exit(1)

    predictions = {}
    total, skipped = 0, 0

    for sector_file in sorted(sector_files):
        sector_name = os.path.basename(sector_file).replace(".json", "")
        print(f"[generate-predictions] Processing {sector_name}…")

        candles_by_ticker = load_historical_candles(sector_file)

        for ticker, candles in candles_by_ticker.items():
            features = _build_features_for_candles(candles)
            if features is None or len(features) < TIMESTEPS:
                skipped += 1
                continue

            try:
                result = predict_ticker(model, features)
                predictions[ticker] = result
                total += 1
            except Exception as e:
                print(f"  [WARN] {ticker}: prediction failed — {e}")
                skipped += 1

    # Read model version from metadata.json if available
    model_version = "2.0.0"
    metadata_path = os.path.join(MODELS_V2_DIR, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            meta = json.load(f)
        # metadata.json uses "version" (written by train-model.py); fall back to
        # legacy "modelVersion" key for backwards compatibility.
        model_version = meta.get("version", meta.get("modelVersion", model_version))

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "date":          today_str,
        "predictionFor": prediction_date,
        "generatedAt":   now_utc,
        "modelVersion":  model_version,
        "predictions":   predictions,
    }

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print()
    print("=" * 60)
    print("[generate-predictions] DONE")
    print(f"  Date:        {today_str}")
    print(f"  For:         {prediction_date}")
    print(f"  Predictions: {total}")
    print(f"  Skipped:     {skipped}")
    print(f"  Output:      {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
