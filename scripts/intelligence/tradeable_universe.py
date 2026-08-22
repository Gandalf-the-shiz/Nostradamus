"""Tradeable universe filter — Mega Yacht / Helios single source of truth.

Fail-closed on missing price and ADV when require_liquidity_profile is true.
Spread and market-cap gates apply only when those fields are actually present
(we do not invent a spread or a cap).
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config" / "tradeable_universe.json"
HIST_DIR = REPO / "data" / "historical"

ADV_SESSIONS = 20
VOL_SESSIONS = 20

# Bare "U" as endswith() bans MU (Micron). Units use a length-gated rule.
# Bare "R" is ignored — it bans KR (Kroger) and many common names. Rights stay on RT.
STRUCTURED_SUFFIX_MIN_LEN = {"U": 4}
IGNORED_SIMPLE_SUFFIXES = frozenset({"R"})

SKIP_HIST_META = frozenset({
    "manifest.json",
    "multiyear-coverage.json",
    "stooq-bulk-coverage.json",
    "_live.json",
})


@lru_cache(maxsize=1)
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "min_price_usd": 5.0,
        "min_adv_usd": 1_000_000.0,
        "min_vol_20": 0.01,
        "max_spread_bps": 50,
        "exclude_suffixes": ["W", "WW", "WS", "WI", "WT", "RT"],
        "exclude_symbols": [],
        "exclude_pattern": "",
        "require_liquidity_profile": True,
        "yacht_tier_min_market_cap_usd": 300_000_000,
    }


def _as_float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        out = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def profile_from_candles(candles: list | None) -> dict:
    """Real 20-session ADV and 20d close-to-close vol. Missing fields stay None."""
    out: dict = {
        "close": None,
        "adv_20": None,
        "vol_20": None,
        "n_adv_sessions": 0,
        "n_vol_sessions": 0,
    }
    if not candles:
        return out
    last = candles[-1] if isinstance(candles[-1], dict) else {}
    out["close"] = _as_float(last.get("close"))

    dollar_vols: list[float] = []
    for row in candles[-ADV_SESSIONS:]:
        if not isinstance(row, dict):
            continue
        close = _as_float(row.get("close"))
        vol = _as_float(row.get("volume"))
        if close is None or vol is None or close <= 0 or vol <= 0:
            continue
        dollar_vols.append(close * vol)
    out["n_adv_sessions"] = len(dollar_vols)
    # Real 20-session average — fewer than 20 sessions is missing, not last-day * volume.
    if len(dollar_vols) >= ADV_SESSIONS:
        out["adv_20"] = float(sum(dollar_vols) / len(dollar_vols))

    closes: list[float] = []
    for row in candles[-(VOL_SESSIONS + 1):]:
        if not isinstance(row, dict):
            continue
        close = _as_float(row.get("close"))
        if close is None or close <= 0:
            continue
        closes.append(close)
    if len(closes) >= VOL_SESSIONS + 1:
        rets = [(closes[i] / closes[i - 1]) - 1.0 for i in range(1, len(closes))]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        out["vol_20"] = float(math.sqrt(var))
        out["n_vol_sessions"] = len(rets)
    return out


def _payload_optional_fields(payload: dict | None) -> dict:
    """Spread / market cap only when the feed actually has them — never invented."""
    extra: dict = {"spread_bps": None, "market_cap": None}
    if not isinstance(payload, dict):
        return extra
    for key in ("spread_bps", "spreadBps", "quoted_spread_bps"):
        extra["spread_bps"] = _as_float(payload.get(key))
        if extra["spread_bps"] is not None:
            break
    if extra["spread_bps"] is None:
        bid = _as_float(payload.get("bid"))
        ask = _as_float(payload.get("ask"))
        mid = None
        if bid is not None and ask is not None and bid > 0 and ask > bid:
            mid = (bid + ask) / 2.0
            extra["spread_bps"] = ((ask - bid) / mid) * 10_000.0
    for key in ("marketCap", "market_cap", "mktcap", "mktCap"):
        extra["market_cap"] = _as_float(payload.get(key))
        if extra["market_cap"] is not None:
            break
    return extra


def _suffix_blocked(sym: str, cfg: dict) -> bool:
    for suf in cfg.get("exclude_suffixes") or []:
        su = str(suf or "").strip().upper()
        if not su or su in IGNORED_SIMPLE_SUFFIXES:
            continue
        min_len = STRUCTURED_SUFFIX_MIN_LEN.get(su)
        if min_len is not None:
            if len(sym) >= min_len and sym.endswith(su):
                return True
            continue
        if sym.endswith(su):
            return True
    # SPAC/unit names (AACU) even if config omitted U. MU (len 2) stays.
    if len(sym) >= 4 and sym.endswith("U"):
        return True
    return False


def _pattern_blocked(sym: str, cfg: dict) -> bool:
    pat = cfg.get("exclude_pattern") or ""
    if not pat:
        return False
    try:
        return bool(re.match(pat, sym, re.I))
    except re.error:
        return False


@lru_cache(maxsize=1)
def _liquidity_cache() -> dict[str, dict]:
    """Last close + real 20d ADV / vol_20 from historical shards (best-effort)."""
    out: dict[str, dict] = {}
    if not HIST_DIR.exists():
        return out
    for fp in sorted(HIST_DIR.glob("*.json")):
        if fp.name.startswith("manifest") or fp.name in SKIP_HIST_META:
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            sym_u = str(sym).upper()
            if sym_u in out:
                continue
            payload = payload or {}
            candles = payload.get("candles") or []
            prof = profile_from_candles(candles)
            prof.update(_payload_optional_fields(payload))
            if prof.get("close") is None and prof.get("adv_20") is None:
                continue
            out[sym_u] = prof
    return out


def is_tradeable(
    symbol: str,
    *,
    close: float | None = None,
    adv_20: float | None = None,
    vol_20: float | None = None,
    spread_bps: float | None = None,
    market_cap: float | None = None,
    cfg: dict | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). Fail-closed on missing close/ADV when required."""
    cfg = cfg or load_config()
    sym = str(symbol or "").strip().upper()
    if not sym or sym == "—":
        return False, "empty"
    if sym in {s.upper() for s in (cfg.get("exclude_symbols") or [])}:
        return False, "excluded_symbol"
    if _suffix_blocked(sym, cfg):
        return False, "warrant_or_unit_suffix"
    if _pattern_blocked(sym, cfg):
        return False, "exclude_pattern"

    prof = {}
    need_prof = (
        close is None or adv_20 is None or vol_20 is None
        or spread_bps is None or market_cap is None
    )
    if need_prof:
        prof = _liquidity_cache().get(sym) or {}
        if close is None:
            close = prof.get("close")
        if adv_20 is None:
            adv_20 = prof.get("adv_20")
        if vol_20 is None:
            vol_20 = prof.get("vol_20")
        if spread_bps is None:
            spread_bps = prof.get("spread_bps")
        if market_cap is None:
            market_cap = prof.get("market_cap")

    require = bool(cfg.get("require_liquidity_profile"))
    min_px = float(cfg.get("min_price_usd") or 0)
    min_adv = float(cfg.get("min_adv_usd") or 0)
    min_vol = float(cfg.get("min_vol_20") or 0)
    max_spread = cfg.get("max_spread_bps")
    min_cap = cfg.get("yacht_tier_min_market_cap_usd")

    if require and close is None:
        return False, "no_liquidity_profile"
    if require and adv_20 is None:
        return False, "no_adv_20"
    if close is not None and min_px and close < min_px:
        return False, f"price<{min_px}"
    if adv_20 is not None and min_adv and adv_20 < min_adv:
        return False, f"adv<{min_adv}"
    if vol_20 is not None and min_vol and vol_20 < min_vol:
        return False, f"vol_20<{min_vol}"
    # Missing vol_20: fail-closed only when the profile is required (same as ADV).
    if require and min_vol and vol_20 is None:
        return False, "no_vol_20"
    # Spread is optional — skip when the feed has no quote. Do not invent it.
    if spread_bps is not None and max_spread is not None:
        try:
            if float(spread_bps) > float(max_spread):
                return False, f"spread_bps>{max_spread}"
        except (TypeError, ValueError):
            pass
    # Market cap is optional — skip when missing. Do not invent it.
    if market_cap is not None and min_cap is not None:
        try:
            if float(market_cap) < float(min_cap):
                return False, f"market_cap<{min_cap}"
        except (TypeError, ValueError):
            pass
    return True, "ok"


def filter_symbols(symbols: list[str], *, cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    out = []
    for s in symbols:
        ok, _ = is_tradeable(s, cfg=cfg)
        if ok:
            out.append(str(s).upper())
    return out


def filter_dataframe(df, symbol_col: str = "symbol", *, cfg: dict | None = None):
    import pandas as pd  # noqa: PLC0415 — optional for suffix-only unit tests
    if df is None or df.empty or symbol_col not in df.columns:
        return df
    cfg = cfg or load_config()
    mask = []
    for sym in df[symbol_col].astype(str):
        ok, _ = is_tradeable(sym, cfg=cfg)
        mask.append(ok)
    filtered = df.loc[mask].copy()
    dropped = len(df) - len(filtered)
    if dropped:
        print(f"[tradeable] dropped {dropped}/{len(df)} symbols", flush=True)
    return filtered


def filter_picks(picks: list[dict], symbol_key: str = "symbol", *, cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    out = []
    for p in picks:
        sym = p.get(symbol_key) or p.get("sym")
        ok, reason = is_tradeable(str(sym or ""), cfg=cfg)
        if ok:
            out.append(p)
        else:
            print(f"[tradeable] drop {sym}: {reason}", flush=True)
    return out
