"""Unit tests for research_reasoner — no API keys required (mock LLM only).

Run:
  $env:PYTHONPATH="scripts"
  python scripts/intelligence/test_research_reasoner.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from intelligence.research_reasoner import (  # noqa: E402
    filter_and_normalize,
    normalize_hypothesis,
    policy_violation,
    reason,
)


SAMPLE_OBS = {
    "observedAt": "2026-06-13T12:00:00Z",
    "edgeProven": False,
    "tradeableSpread": -0.012,
    "alphaSpread": -0.008,
    "alphaIcir": 0.3,
    "liveIcMean": 0.025,
    "liveIcDays": 22,
    "forwardPromotionOk": False,
    "concentrationSymbols": ["SDOT", "JDZG", "XOS"],
    "decayedSleeves": ["pead"],
}


MOCK_LLM_RESPONSE = json.dumps([
    {
        "type": "concentration_fix",
        "hypothesis": (
            "If we run alpha_neutral_wide genomes with liquidity caps, "
            "tradeable quintile spread will improve because concentration in warrants drops"
        ),
        "successCriteria": {
            "holdout_mean_quintile_spread_gt": 0.0,
            "reject_if_sharpe_high_spread_negative": True,
        },
        "experiment": {
            "route": "mad_scientist",
            "params": {"genomes": 120, "promote": 0, "profile": "alpha_neutral_wide"},
        },
        "priority": 1,
        "reasoning": "Winners cluster in SDOT/JDZG/XOS; transfer coefficient likely low.",
        "confidence": 0.65,
    },
    {
        "type": "alpha_tweak",
        "hypothesis": "If we respawn v1 genomes with higher breadth, spread will improve because more bets",
        "successCriteria": {"holdout_mean_quintile_spread_gt": 0.0},
        "experiment": {"route": "walkforward_engine", "params": {"signal": "alpha"}},
        "priority": 2,
        "reasoning": "bad policy",
        "confidence": 0.9,
    },
])


def test_policy_violation_respawn():
    assert policy_violation("We should respawn v1 genomes") is not None


def test_policy_violation_readiness():
    assert policy_violation("weaken readiness gate for faster promotion") is not None


def test_normalize_valid():
    raw = json.loads(MOCK_LLM_RESPONSE)[0]
    norm = normalize_hypothesis(raw, SAMPLE_OBS)
    assert norm is not None
    assert norm["type"] == "concentration_fix"
    assert norm["route"] == "mad_scientist"
    assert norm["source"] == "llm"
    assert "holdout_mean_quintile_spread_gt" in norm["successCriteria"]


def test_filter_rejects_policy_violation():
    parsed = json.loads(MOCK_LLM_RESPONSE)
    hyps, rejections = filter_and_normalize(parsed, SAMPLE_OBS)
    assert len(hyps) == 1
    assert hyps[0]["type"] == "concentration_fix"
    assert any("invalid_or_policy" in r for r in rejections)


def test_reason_mock():
    hyps, meta = reason(SAMPLE_OBS, mock_response=MOCK_LLM_RESPONSE)
    assert meta["backend"] == "mock"
    assert meta["ok"] is True
    assert len(hyps) == 1


def test_promotion_gate_forced_observe_only():
    raw = {
        "type": "promotion_gate",
        "hypothesis": "If edge remains unproven, we will observe until forward spread turns positive because gates protect capital",
        "successCriteria": {"edge_proven": True},
        "experiment": {"route": "walkforward_engine", "params": {}},
        "priority": 1,
        "reasoning": "edge_proven false",
        "confidence": 0.95,
    }
    norm = normalize_hypothesis(raw, SAMPLE_OBS)
    assert norm is not None
    assert norm["route"] == "observe_only"
    assert norm["status"] == "blocked"


def run_all() -> int:
    tests = [
        test_policy_violation_respawn,
        test_policy_violation_readiness,
        test_normalize_valid,
        test_filter_rejects_policy_violation,
        test_reason_mock,
        test_promotion_gate_forced_observe_only,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERR  {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_all())
