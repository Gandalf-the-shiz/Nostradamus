"""Ultimate Model — meta-reasoning agent over Investor Arena v1/v2 results.

Reads cumulative ledgers + daily reasoning, produces improvement hypotheses.
Always scheming (paper/research); does not auto-change live gates.

Usage:
  python scripts/intelligence/ultimate_model.py
  python scripts/intelligence/ultimate_model.py --tick
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

OUT_DIR = REPO / "data" / "intelligence" / "ultimate_model"
REPORT_PATH = OUT_DIR / "latest_report.json"
JOURNAL_PATH = OUT_DIR / "journal.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _analyze_version(version: str) -> dict:
    from intelligence.arena.ledger import ranked_traders, version_summary
    from intelligence.arena.paths import ledger_path

    ranked = ranked_traders(version)
    summary = version_summary(version)
    zero_days = sum(1 for r in ranked if not (r.get("daily") or []))
    families = Counter(r.get("family") for r in ranked[:30])
    avg_trades = 0.0
    if ranked:
        avg_trades = sum((r.get("daily") or [{}])[-1].get("nTrades", 0) for r in ranked) / len(ranked)

    sym_freq = Counter()
    for r in ranked[:40]:
        for d in (r.get("daily") or [])[-1:]:
            for t in d.get("trades") or []:
                sym_freq[t.get("symbol")] += 1

    return {
        "version": version,
        "summary": summary,
        "zeroHistory": zero_days,
        "topFamilies": families.most_common(5),
        "avgTradesPerPulse": round(avg_trades, 2),
        "topSymbols": sym_freq.most_common(8),
        "top5": [
            {
                "traderId": r.get("traderId"),
                "family": r.get("family"),
                "cumulativeReturnPct": r.get("cumulativeReturnPct"),
                "selectionMode": (r.get("genome") or {}).get("selection_mode"),
            }
            for r in ranked[:5]
        ],
        "ledgerExists": ledger_path(version).exists(),
    }


def _forward_context() -> dict:
    """What Treasure Droid actually reasons over: forward fleet + live IC + alpha + readiness."""
    import os

    live_root = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))

    def _L(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    fleet = _L(REPO / "data" / "fleet" / "summary.json")
    ic = _L(REPO / "data" / "accuracy" / "v3_live_ic.json")
    alpha = _L(REPO / "data" / "accuracy" / "alpha_ic.json")
    sleeve_ic = _L(REPO / "data" / "accuracy" / "sleeve_ic.json")
    ms_loop = _L(REPO / "data" / "intelligence" / "historical" / "loop_state.json")
    readiness = _L(live_root / "data" / "gate" / "readiness.json")
    blend = alpha.get("blended_neutralized") or {}
    decayed = [
        k for k, v in (sleeve_ic.get("forward") or {}).get("by_sleeve", {}).items()
        if v.get("decayed")
    ]
    return {
        "fleetLeader": fleet.get("leader"),
        "fleetAgents": fleet.get("agents") or [],
        "liveIcDays": ic.get("n_days") or ic.get("nDays") or 0,
        "liveIcMean": ic.get("mean_ic") if ic.get("mean_ic") is not None else ic.get("meanRankIc"),
        "alphaSpread": blend.get("mean_quintile_spread"),
        "alphaIcir": blend.get("icir"),
        "sleeveWeightMode": sleeve_ic.get("weight_mode"),
        "sleeveForwardDays": (sleeve_ic.get("forward") or {}).get("n_days") or 0,
        "decayedSleeves": decayed,
        "madScientistCycle": ms_loop.get("cycle"),
        "madScientistProfile": ms_loop.get("lastProfile"),
        "madScientistChampions": (ms_loop.get("champions") or [])[:3],
        "livePermitted": bool(readiness.get("liveTradingPermitted")),
    }


def _captain_recommendations(ctx: dict) -> list[dict]:
    """Captain allocates. No coding tickets, no Cursor spawn rules, no auto-approve."""
    recs: list[dict] = []
    leader = ctx.get("fleetLeader") or {}
    laggards = [a for a in (ctx.get("fleetAgents") or []) if a.get("returnPct") is not None]
    worst = laggards[-1] if laggards else {}

    if leader:
        recs.append({
            "kind": "set_weight",
            "priority": "medium",
            "area": "allocation",
            "finding": "Capital should follow the forward-paper leader of the crew, not sim winners.",
            "action": "set_weight: raise paper allocation to the leading forward agent; cut laggards.",
            "detail": f"Leader {leader.get('name')} {leader.get('returnPct')}% | laggard {worst.get('name')} {worst.get('returnPct')}%",
        })

    decayed = ctx.get("decayedSleeves") or []
    if decayed:
        recs.append({
            "kind": "set_weight",
            "priority": "medium",
            "area": "allocation",
            "finding": "Per-sleeve forward IC shows decay — those sleeves should not run the book.",
            "action": f"set_weight: keep {', '.join(decayed)} at 0 until trailing forward IC is positive.",
            "detail": f"weight mode {ctx.get('sleeveWeightMode')}",
        })

    days = int(ctx.get("sleeveForwardDays") or 0)
    if days < 20:
        recs.append({
            "kind": "shadow_new",
            "priority": "info",
            "area": "allocation",
            "finding": f"Sleeve factory has {days}/20 forward days — nothing earns a live weight yet.",
            "action": "shadow_new: hold all sleeves in shadow until 20 forward days and a positive ICIR.",
            "detail": f"weight mode {ctx.get('sleeveWeightMode')}",
        })

    if worst and (worst.get("returnPct") or 0) < 0 and worst.get("id"):
        recs.append({
            "kind": "retire",
            "priority": "medium",
            "area": "allocation",
            "finding": "A forward-paper agent is underwater — prune should retire it after 20 days.",
            "action": f"retire: {worst.get('id')} if 20-day forward return stays ≤ 0.",
            "detail": f"{worst.get('name')} {worst.get('returnPct')}%",
        })
    return recs


def _build_recommendations(v1: dict, v2: dict, compare: dict) -> list[dict]:
    """Allocation recs only. No live_gate / data_pipelines tickets, no Cursor spawnSpec."""
    recs: list[dict] = []
    top_syms = [s for s, _ in (v1.get("topSymbols") or [])[:3] if s]
    if top_syms:
        recs.append({
            "kind": "retire",
            "priority": "medium",
            "area": "allocation",
            "finding": f"Sim winners still cluster in {top_syms} (often warrants/units).",
            "action": "retire: keep those names out of the live panel via the fail-closed universe; do not spawn a new arena.",
            "detail": "Helios tradeable filter (suffix + 20d ADV) is the capital path, not another genome.",
        })

    try:
        recs.extend(_captain_recommendations(_forward_context()))
    except Exception as exc:  # noqa: BLE001
        print(f"[treasure-droid] captain recs skipped: {exc}", flush=True)
    return recs


def _llm_narrative(payload: dict) -> str | None:
    try:
        from npu_llm import generate_text
        prompt = (
            "You are Treasure Droid, a rusted robot-pirate captain commanding a fleet of ML "
            "trading agents hunting market gold. Given the arena + forward fleet stats, write 3 short "
            "paragraphs: what's working, what's failing, and the single most valuable next build "
            "(e.g. a new data pipeline, a re-weighted Treasure Arena arm, or promoting a model). "
            "Be skeptical of simulated returns \u2014 only forward paper is real treasure.\n\n"
            f"DATA:\n{json.dumps(payload, indent=2)[:6000]}"
        )
        return generate_text(prompt, max_tokens=600)
    except Exception:
        return None


def run_tick() -> dict:
    from intelligence.arena.ledger import compare_series
    from intelligence.arena.operating import ensure_operating_model, operating_status

    ensure_operating_model()
    op = operating_status()
    v1 = _analyze_version("v1")
    v2 = _analyze_version("v2")
    compare = compare_series()
    recommendations = _build_recommendations(v1, v2, compare)

    narrative = (
        f"Treasure Droid tick {_now()} — captain of the fleet, hunting market gold (sim arena scoreboard; "
        f"forward paper is the only real treasure). "
        f"v1 {v1['summary'].get('meanCumulativePct')}% vs v2 {v2['summary'].get('meanCumulativePct')}% "
        f"(v2 beating v1: {compare.get('v2BeatingV1')}). "
        f"Operating: pulse {op.get('pulseVersions')}; champion {op.get('champion')}; "
        f"challenger {op.get('challenger')}; archived {op.get('archived')}. "
        "v1/v2 frozen; Megamind evolves champion + optional challenger; harvest uses all pools."
    )
    llm = _llm_narrative({"v1": v1, "v2": v2, "compare": compare, "recommendations": recommendations})
    if llm:
        narrative += "\n\nLLM synthesis:\n" + llm

    doc = {
        "generatedAt": _now(),
        "status": "scheming",
        "v1": v1,
        "v2": v2,
        "compare": compare,
        "recommendations": recommendations,
        "narrative": narrative,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    with JOURNAL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _now(), "narrative": narrative[:2000]}) + "\n")
    print(f"[ultimate-model] report written {REPORT_PATH}", flush=True)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true")
    args = ap.parse_args()
    run_tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
