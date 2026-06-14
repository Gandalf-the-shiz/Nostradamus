"""Autonomous Research Machine — meta-controller for Treasure Droid.

Closed loop: OBSERVE forward metrics → REASON (LLM + rule fallback) →
EXPERIMENT (walkforward_engine / mad_scientist) → MEASURE (tradeable spread) →
DECIDE (accept/reject) → ACT (log + optional fleet/arena dispatch).

Does not weaken readiness gates or open live trading.

Usage:
  python scripts/intelligence/research_controller.py --tick
  python scripts/intelligence/research_controller.py --observe-only
  python scripts/intelligence/research_controller.py --tick --apply
  python scripts/intelligence/research_controller.py --tick --no-llm
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

RESEARCH_DIR = REPO / "data" / "intelligence" / "research"
CYCLE_PATH = RESEARCH_DIR / "latest_cycle.json"
HYPOTHESES_PATH = RESEARCH_DIR / "hypotheses.jsonl"
VERDICTS_PATH = RESEARCH_DIR / "verdicts.jsonl"
PENDING_PATH = RESEARCH_DIR / "pending.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        pass
    return default if default is not None else {}


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def _hypothesis_id(statement: str, htype: str) -> str:
    raw = f"{htype}|{statement[:120]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def observe() -> dict:
    """Gather forward-truth metrics from all scoreboards."""
    import os

    from intelligence.forward_gate import (
        forward_promotion_ok,
        load_forward_ic,
        load_honest_eval,
        load_readiness,
    )

    live_root = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))

    def _L(p: Path) -> dict:
        return _load_json(p, {})

    fleet = _L(REPO / "data" / "fleet" / "summary.json")
    ic = _L(REPO / "data" / "accuracy" / "v3_live_ic.json") or load_forward_ic()
    alpha = _L(REPO / "data" / "accuracy" / "alpha_ic.json")
    sleeve_ic = _L(REPO / "data" / "accuracy" / "sleeve_ic.json")
    readiness = load_readiness()
    honest = load_honest_eval()
    ms_loop = _L(REPO / "data" / "intelligence" / "historical" / "loop_state.json")
    lab = _L(REPO / "data" / "intelligence" / "historical" / "lab_results.json")

    blend = alpha.get("blended_neutralized") or alpha.get("neutralized_edge") or {}
    verdict = honest.get("verdict") or {}
    tt = honest.get("test_tradeable") or {}
    paper = readiness.get("paperSummary") or {}
    fwd_ok, fwd_reasons = forward_promotion_ok(require_edge_proven=False)

    arena_compare = {}
    try:
        from intelligence.arena.ledger import compare_series
        arena_compare = compare_series()
    except Exception:
        pass

    concentration: list[str] = []
    try:
        from intelligence.ultimate_model import _analyze_version
        v1 = _analyze_version("v1")
        concentration = [s for s, _ in (v1.get("topSymbols") or [])[:3] if s]
    except Exception:
        pass

    decayed = [
        k for k, v in (sleeve_ic.get("forward") or {}).get("by_sleeve", {}).items()
        if v.get("decayed")
    ]

    return {
        "observedAt": _now(),
        "edgeProven": bool(verdict.get("edge_proven")),
        "tradeableSpread": tt.get("quintile_spread") or tt.get("mean_quintile_spread"),
        "alphaSpread": blend.get("mean_quintile_spread"),
        "alphaIcir": blend.get("icir"),
        "liveIcMean": ic.get("mean_ic") if ic.get("mean_ic") is not None else ic.get("meanRankIc"),
        "liveIcDays": ic.get("n_days") or ic.get("nDays") or 0,
        "forwardPromotionOk": fwd_ok,
        "forwardBlockReasons": fwd_reasons,
        "paperSharpe": paper.get("sharpe"),
        "paperReturnPct": paper.get("totalReturnPct"),
        "fleetLeader": fleet.get("leader"),
        "fleetAgentCount": len(fleet.get("agents") or []),
        "decayedSleeves": decayed,
        "concentrationSymbols": concentration,
        "madScientistCycle": ms_loop.get("cycle"),
        "madScientistHeldUp": lab.get("topSelectionHeldUp"),
        "arenaV2BeatingV1": arena_compare.get("v2BeatingV1"),
        "livePermitted": bool(readiness.get("liveTradingPermitted")),
        "provenance": {
            "honest_eval": str(live_root / "reports" / "honest_eval.json"),
            "alpha_ic": str(REPO / "data" / "accuracy" / "alpha_ic.json"),
            "fleet": str(REPO / "data" / "fleet" / "summary.json"),
        },
    }


def hypothesize_rules(obs: dict) -> list[dict]:
    """Rule-based hypotheses — fallback when LLM unavailable or returns nothing valid."""
    hyps: list[dict] = []

    alpha_spread = obs.get("alphaSpread")
    if alpha_spread is not None and alpha_spread < 0:
        stmt = "Neutralized alpha signal produces positive holdout quintile spread on historical panel"
        hyps.append({
            "id": _hypothesis_id(stmt, "alpha_neutralization"),
            "type": "alpha_neutralization",
            "statement": stmt,
            "rationale": f"Live alpha spread {alpha_spread} is negative — test neutralized alpha on locked holdout",
            "successCriteria": {
                "holdout_mean_quintile_spread_gt": 0.0,
                "holdout_mean_ic_gt": 0.0,
                "reject_if_sharpe_high_spread_negative": True,
            },
            "route": "walkforward_engine",
            "params": {"signal": "alpha", "selection_frac": 0.6},
            "status": "pending",
            "preRegisteredAt": _now(),
        })

    if not obs.get("edgeProven"):
        stmt = "Model promotion remains blocked until forward tradeable spread proves positive"
        hyps.append({
            "id": _hypothesis_id(stmt, "promotion_gate"),
            "type": "promotion_gate",
            "statement": stmt,
            "rationale": (
                f"edge_proven=false; tradeable spread={obs.get('tradeableSpread')}; "
                f"forward_ok={obs.get('forwardPromotionOk')}"
            ),
            "successCriteria": {"edge_proven": True, "holdout_mean_quintile_spread_gt": 0.0},
            "route": "observe_only",
            "params": {},
            "status": "blocked",
            "preRegisteredAt": _now(),
        })

    concentration = obs.get("concentrationSymbols") or []
    if concentration:
        stmt = "Liquidity-aware alpha-neutral genomes reduce symbol concentration without killing holdout spread"
        hyps.append({
            "id": _hypothesis_id(stmt, "genome_concentration"),
            "type": "genome_search",
            "statement": stmt,
            "rationale": f"Arena winners cluster in {concentration}",
            "successCriteria": {
                "holdout_mean_quintile_spread_gt": 0.0,
                "holdout_sharpe_gt": 0.0,
                "reject_if_sharpe_high_spread_negative": True,
            },
            "route": "mad_scientist",
            "params": {"genomes": 120, "promote": 0, "profile": "alpha_neutral_wide"},
            "status": "pending",
            "preRegisteredAt": _now(),
        })

    decayed = obs.get("decayedSleeves") or []
    if decayed:
        stmt = "Decayed sleeves stay at zero weight until trailing forward IC recovers"
        hyps.append({
            "id": _hypothesis_id(stmt, "sleeve_decay"),
            "type": "sleeve_decay",
            "statement": stmt,
            "rationale": f"Decayed sleeves: {', '.join(decayed)}",
            "successCriteria": {"forward_ic_positive": True},
            "route": "act_only",
            "params": {"sleeves": decayed},
            "status": "pending",
            "preRegisteredAt": _now(),
        })

    raw_spread = obs.get("tradeableSpread")
    if raw_spread is not None and raw_spread < 0 and len(hyps) < 4:
        stmt = "Raw ML edge alone is not tradeable; blended neutralized sleeves must carry the book"
        hyps.append({
            "id": _hypothesis_id(stmt, "raw_edge_negative"),
            "type": "raw_edge_check",
            "statement": stmt,
            "rationale": f"Honest eval tradeable spread={raw_spread}",
            "successCriteria": {"holdout_mean_quintile_spread_gt": 0.0},
            "route": "walkforward_engine",
            "params": {"signal": "edge", "selection_frac": 0.6},
            "status": "pending",
            "preRegisteredAt": _now(),
        })

    return hyps[:4]


def hypothesize(obs: dict, *, use_llm: bool = True) -> tuple[list[dict], dict]:
    """Try LLM reasoning first; fall back to rules. Returns (hypotheses, reasonMeta)."""
    meta: dict = {"source": "rules", "backend": "rules"}
    if use_llm:
        try:
            from intelligence.research_reasoner import llm_disabled, reason
            if not llm_disabled():
                llm_hyps, llm_meta = reason(obs)
                meta = {**llm_meta, "source": "llm" if llm_hyps else "rules_fallback"}
                if llm_hyps:
                    print(
                        f"[research] LLM reasoned {len(llm_hyps)} hypotheses via {llm_meta.get('backend')}",
                        flush=True,
                    )
                    return llm_hyps, meta
                print(
                    f"[research] LLM unavailable/empty ({llm_meta.get('reason') or llm_meta.get('backend')}) — rules fallback",
                    flush=True,
                )
        except Exception as exc:
            meta = {"source": "rules_fallback", "error": str(exc)[:200]}
            print(f"[research] LLM error — rules fallback: {exc}", flush=True)

    return hypothesize_rules(obs), meta


def _recent_verdict_ids(cooldown_hours: float = 6.0) -> set[str]:
    """Skip re-running experiments for hypotheses judged recently."""
    ids: set[str] = set()
    if not VERDICTS_PATH.exists():
        return ids
    cutoff = datetime.now(timezone.utc).timestamp() - cooldown_hours * 3600
    for ln in VERDICTS_PATH.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            row = json.loads(ln)
            at = row.get("at") or ""
            if not at or not row.get("hypothesisId"):
                continue
            ts = datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
            if ts >= cutoff:
                ids.add(row["hypothesisId"])
        except (json.JSONDecodeError, ValueError):
            continue
    return ids


def run_experiment(hyp: dict) -> dict:
    """Route hypothesis to the correct experiment runner."""
    route = hyp.get("route") or ""
    params = dict(hyp.get("params") or {})

    if route == "walkforward_engine":
        from intelligence.walkforward_engine import run as wf_run
        return wf_run(
            signal=params.get("signal", "alpha"),
            selection_frac=params.get("selection_frac"),
            hypothesis_id=hyp.get("id"),
        )

    if route == "mad_scientist":
        from intelligence.historical.walkforward_lab import run as lab_run
        return lab_run(
            genomes=int(params.get("genomes") or 120),
            promote=int(params.get("promote") or 0),
        )

    if route in ("observe_only", "act_only"):
        return {"ok": True, "engine": route, "message": "no experiment required"}

    return {"ok": False, "message": f"unknown route {route}"}


def decide(hyp: dict, result: dict) -> dict:
    """Apply pre-registered success criteria; auto-reject Sharpe-without-spread."""
    criteria = hyp.get("successCriteria") or {}
    htype = hyp.get("type") or ""

    if htype == "promotion_gate":
        return {
            "verdict": "reject",
            "reasons": ["edge_not_proven_gate_active"],
            "evidence": {"edgeProven": False},
        }

    if htype == "sleeve_decay":
        sleeves = (hyp.get("params") or {}).get("sleeves") or []
        return {
            "verdict": "accept",
            "reasons": ["zero_weight_decayed_sleeves"],
            "evidence": {"sleeves": sleeves, "action": "recommend_zero_weight"},
        }

    if not result.get("ok"):
        return {
            "verdict": "reject",
            "reasons": [result.get("message") or "experiment_failed"],
            "evidence": result,
        }

    holdout = result.get("holdout") or {}
    if result.get("engine") == "walkforward_engine" or "holdout" in result:
        if "holdout" not in result and result.get("survivors") is not None:
            holdout = {
                "sharpe": (result.get("leaderboard") or [{}])[0].get("holdSharpe"),
                "mean_quintile_spread": None,
            }
        from intelligence.walkforward_engine import promotion_verdict
        min_spread = float(criteria.get("holdout_mean_quintile_spread_gt", 0.0))
        label, reasons = promotion_verdict(holdout, min_spread=min_spread)

        if criteria.get("reject_if_sharpe_high_spread_negative"):
            spread = holdout.get("mean_quintile_spread")
            icir = holdout.get("icir")
            if icir and icir > 0.5 and (spread is None or spread <= 0):
                label = "reject"
                reasons = reasons + ["sharpe_proxy_high_but_spread_negative"]

        min_ic = criteria.get("holdout_mean_ic_gt")
        if min_ic is not None:
            mic = holdout.get("mean_ic")
            if mic is None or mic <= float(min_ic):
                label = "reject"
                reasons.append(f"holdout_mean_ic={mic}<={min_ic}")

        return {"verdict": label, "reasons": reasons, "evidence": {"holdout": holdout}}

    best = (result.get("leaderboard") or [{}])[0]
    hold_sharpe = best.get("holdSharpe")
    if criteria.get("holdout_sharpe_gt") is not None:
        if hold_sharpe is None or hold_sharpe <= float(criteria["holdout_sharpe_gt"]):
            return {
                "verdict": "reject",
                "reasons": [f"holdout_sharpe={hold_sharpe}"],
                "evidence": {"best": best},
            }

    if criteria.get("reject_if_sharpe_high_spread_negative"):
        return {
            "verdict": "reject",
            "reasons": ["mad_scientist_sharpe_without_tradeable_spread_gate"],
            "evidence": {"best": best, "note": "Genome lab lacks per-day spread; requires walkforward confirm"},
        }

    return {
        "verdict": "reject",
        "reasons": ["insufficient_evidence_for_promotion"],
        "evidence": {"leaderboard_head": (result.get("leaderboard") or [])[:3]},
    }


def act(hyp: dict, decision: dict, *, apply: bool = False) -> dict:
    """Log verdict; optionally dispatch arena/fleet actions (paper only)."""
    import os

    action = {"applied": False, "dispatch": None, "note": "dry_run"}

    if decision.get("verdict") != "accept":
        return action

    htype = hyp.get("type") or ""
    if htype == "sleeve_decay" and apply:
        action["dispatch"] = "sleeve_zero_weight"
        action["note"] = "Recommend zero weight for decayed sleeves (manual confirm in alpha engine)"
        action["applied"] = False

    if htype in ("genome_search", "genome_concentration", "concentration_fix") and apply:
        action["dispatch"] = "mad_scientist_promote_shadow"
        action["note"] = "Run mad_scientist with --promote after walkforward spread confirm"
        action["applied"] = False

    if htype in ("alpha_neutralization", "alpha_tweak") and apply:
        action["dispatch"] = "megamind_recommendation"
        action["note"] = "Forward-positive alpha spread — queue Megamind champion update (human approve)"
        action["applied"] = False

    bridge = (os.getenv("RESEARCH_MEGAMIND_BRIDGE") or "").strip().lower() in ("1", "true", "yes")
    if bridge or apply:
        try:
            from intelligence.research_reasoner import enqueue_megamind_proposal
            meg = enqueue_megamind_proposal(hyp, decision, dry_run=not (apply and bridge))
            action["megamindBridge"] = meg
            if meg.get("queued"):
                action["dispatch"] = action.get("dispatch") or "megamind_proposed"
                action["note"] = f"Megamind proposal {meg.get('recommendationId')} — human approve required"
        except Exception as exc:
            action["megamindBridge"] = {"queued": False, "error": str(exc)[:200]}

    return action


def log_verdict(hyp: dict, decision: dict, action: dict, result: dict) -> dict:
    row = {
        "at": _now(),
        "hypothesisId": hyp.get("id"),
        "type": hyp.get("type"),
        "statement": hyp.get("statement"),
        "verdict": decision.get("verdict"),
        "reasons": decision.get("reasons"),
        "evidence": decision.get("evidence"),
        "action": action,
        "experimentEngine": result.get("engine") or result.get("mantra"),
    }
    _append_jsonl(VERDICTS_PATH, row)
    try:
        from intelligence.brain.journal import append_backtest
        append_backtest({
            "kind": "research_cycle",
            "title": f"Research - {hyp.get('type')} -> {decision.get('verdict')}",
            "insight": hyp.get("statement", "")[:200],
            "metrics": {
                "verdict": decision.get("verdict"),
                "reasons": decision.get("reasons"),
            },
            "caveat": "Research controller verdict — forward paper remains scoreboard.",
            "source": "scripts/intelligence/research_controller.py",
        })
    except Exception as exc:
        print(f"[research] brain journal skip: {exc}", flush=True)
    return row


def _log_llm_backend(use_llm: bool) -> None:
    if not use_llm:
        print("[research] LLM backend: skipped (--no-llm)", flush=True)
        return
    try:
        from intelligence.research_reasoner import resolve_llm_backend
        print(f"[research] LLM backend: {resolve_llm_backend()}", flush=True)
    except Exception as exc:
        print(f"[research] LLM backend: unknown ({exc})", flush=True)


def tick(*, apply: bool = False, max_experiments: int = 2, use_llm: bool = True) -> dict:
    """Full OBSERVE → REASON → EXPERIMENT → DECIDE → ACT cycle."""
    _log_llm_backend(use_llm)
    obs = observe()
    hyps, reason_meta = hypothesize(obs, use_llm=use_llm)
    decided_ids = _recent_verdict_ids()

    for h in hyps:
        _append_jsonl(HYPOTHESES_PATH, {**h, "cycleAt": _now()})

    experiments_run = 0
    verdicts: list[dict] = []

    for hyp in hyps:
        if hyp.get("id") in decided_ids:
            continue
        if experiments_run >= max_experiments:
            break
        if hyp.get("route") in ("observe_only",):
            decision = decide(hyp, {"ok": True, "engine": "observe_only"})
            action = act(hyp, decision, apply=apply)
            verdicts.append(log_verdict(hyp, decision, action, {}))
            experiments_run += 1
            continue
        if hyp.get("route") == "act_only":
            decision = decide(hyp, {"ok": True, "engine": "act_only"})
            action = act(hyp, decision, apply=apply)
            verdicts.append(log_verdict(hyp, decision, action, {}))
            experiments_run += 1
            continue

        print(f"[research] experiment {hyp.get('type')} via {hyp.get('route')}", flush=True)
        result = run_experiment(hyp)
        decision = decide(hyp, result)
        action = act(hyp, decision, apply=apply)
        verdicts.append(log_verdict(hyp, decision, action, result))
        experiments_run += 1

    cycle = {
        "generatedAt": _now(),
        "observation": obs,
        "hypotheses": hyps,
        "reasoning": reason_meta,
        "verdictsThisCycle": verdicts,
        "experimentsRun": experiments_run,
        "applyMode": apply,
        "llmEnabled": use_llm,
        "status": "ok",
    }
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    CYCLE_PATH.write_text(json.dumps(cycle, indent=2), encoding="utf-8")
    print(
        f"[research] cycle done: {len(hyps)} hypotheses, {experiments_run} experiments, "
        f"{sum(1 for v in verdicts if v.get('verdict') == 'accept')} accepted",
        flush=True,
    )
    return cycle


def main() -> int:
    try:
        from app_secrets import load_secrets
        load_secrets()
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Treasure Droid research meta-controller")
    ap.add_argument("--tick", action="store_true", help="run full observe→decide cycle")
    ap.add_argument("--observe-only", action="store_true", help="print observation JSON only")
    ap.add_argument("--apply", action="store_true", help="allow dispatch actions (still paper-only)")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM reasoning; use rule-based hypotheses only")
    ap.add_argument("--max-experiments", type=int, default=2)
    args = ap.parse_args()

    if args.observe_only:
        print(json.dumps(observe(), indent=2))
        return 0

    if args.tick or not args.observe_only:
        tick(apply=args.apply, max_experiments=max(1, args.max_experiments), use_llm=not args.no_llm)
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
