"""Unit tests for the fail-closed tradeable universe (Helios Phase 0).

Run from repo root:
  PYTHONPATH=scripts python scripts/intelligence/test_tradeable_universe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from intelligence.tradeable_universe import (  # noqa: E402
    is_tradeable,
    profile_from_candles,
)


CFG = {
    "min_price_usd": 5.0,
    "min_adv_usd": 1_000_000.0,
    "min_vol_20": 0.01,
    "max_spread_bps": 50,
    "exclude_suffixes": ["W", "WW", "WS", "WI", "WT", "RT", "U", "R"],
    "exclude_symbols": [],
    "exclude_pattern": "",
    "require_liquidity_profile": True,
    "yacht_tier_min_market_cap_usd": 300_000_000,
}


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_mu_tradeable_by_suffix() -> None:
    ok, reason = is_tradeable("MU", close=80.0, adv_20=50_000_000.0, vol_20=0.02, cfg=CFG)
    _assert(ok, f"MU must pass suffix (was banned by endswith U): {reason}")


def test_kr_not_banned_by_bare_r() -> None:
    ok, reason = is_tradeable("KR", close=50.0, adv_20=20_000_000.0, vol_20=0.015, cfg=CFG)
    _assert(ok, f"KR must not be banned by bare R suffix: {reason}")


def test_warrant_blocked() -> None:
    ok, reason = is_tradeable("XXXW", close=10.0, adv_20=5_000_000.0, vol_20=0.02, cfg=CFG)
    _assert(not ok, "XXXW must be blocked as a warrant")
    _assert(reason == "warrant_or_unit_suffix", f"unexpected reason {reason}")


def test_unit_length_gated() -> None:
    ok, reason = is_tradeable("AACU", close=10.0, adv_20=5_000_000.0, vol_20=0.02, cfg=CFG)
    _assert(not ok and reason == "warrant_or_unit_suffix", f"AACU should be a unit: {reason}")


def test_missing_liquidity_fails_closed() -> None:
    ok, reason = is_tradeable("NEVERHEARD", cfg=CFG)
    _assert(not ok, "missing liquidity must fail when require_liquidity_profile")
    _assert(reason in {"no_liquidity_profile", "no_adv_20", "no_vol_20"}, f"got {reason}")


def test_missing_adv_fails_when_price_present() -> None:
    ok, reason = is_tradeable("FAKE", close=12.0, cfg=CFG)
    _assert(not ok, "price without ADV must fail-closed")
    _assert(reason in {"no_adv_20", "no_vol_20"}, f"got {reason}")


def test_adv_uses_multiple_candles() -> None:
    candles = []
    for i in range(20):
        # Distinct dollar volumes so last-day close*volume cannot match the mean.
        candles.append({"close": 10.0 + i, "volume": 100_000.0 + i * 1_000.0})
    prof = profile_from_candles(candles)
    last_dv = candles[-1]["close"] * candles[-1]["volume"]
    mean_dv = sum(c["close"] * c["volume"] for c in candles) / 20.0
    _assert(prof["adv_20"] is not None, "20 candles must produce adv_20")
    _assert(abs(prof["adv_20"] - mean_dv) < 1e-6, f"adv_20 {prof['adv_20']} != mean {mean_dv}")
    _assert(abs(prof["adv_20"] - last_dv) > 1.0, "adv_20 must not be last-day close*volume")
    _assert(prof["n_adv_sessions"] == 20, f"expected 20 sessions, got {prof['n_adv_sessions']}")


def test_adv_missing_when_fewer_than_20() -> None:
    candles = [{"close": 10.0, "volume": 1_000_000.0} for _ in range(7)]
    prof = profile_from_candles(candles)
    _assert(prof["adv_20"] is None, "fewer than 20 sessions is missing ADV, not last-day dollar volume")
    _assert(prof["close"] == 10.0, "close still comes from last bar")


def test_vol_20_from_closes() -> None:
    # Alternating +2% / -2% → daily vol around 0.02
    px = 100.0
    candles = [{"close": px, "volume": 1_000_000.0}]
    for i in range(20):
        px *= 1.02 if i % 2 == 0 else 0.98
        candles.append({"close": px, "volume": 1_000_000.0})
    prof = profile_from_candles(candles)
    _assert(prof["vol_20"] is not None, "21 closes must produce vol_20")
    _assert(prof["vol_20"] > 0.01, f"expected noticeable vol, got {prof['vol_20']}")


def test_spread_skipped_when_missing() -> None:
    ok, reason = is_tradeable(
        "MU", close=80.0, adv_20=50_000_000.0, vol_20=0.02, cfg=CFG
    )
    _assert(ok, f"missing spread must skip that gate, not fail: {reason}")


def test_wide_spread_blocked_when_present() -> None:
    ok, reason = is_tradeable(
        "MU", close=80.0, adv_20=50_000_000.0, vol_20=0.02, spread_bps=200.0, cfg=CFG
    )
    _assert(not ok and reason.startswith("spread_bps"), f"wide spread should block: {reason}")


def main() -> int:
    tests = [
        test_mu_tradeable_by_suffix,
        test_kr_not_banned_by_bare_r,
        test_warrant_blocked,
        test_unit_length_gated,
        test_missing_liquidity_fails_closed,
        test_missing_adv_fails_when_price_present,
        test_adv_uses_multiple_candles,
        test_adv_missing_when_fewer_than_20,
        test_vol_20_from_closes,
        test_spread_skipped_when_missing,
        test_wide_spread_blocked_when_present,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
