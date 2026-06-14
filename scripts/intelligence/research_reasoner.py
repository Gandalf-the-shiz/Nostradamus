"""LLM meta-controller for the Autonomous Research Machine.

Takes structured ``observe()`` output and emits falsifiable hypotheses with
pre-registered success criteria. Falls back gracefully when no LLM is configured.

Providers (first match wins):
  1. OpenAI-compatible chat API (OPENAI_API_KEY + optional OPENAI_BASE_URL)
  2. Anthropic Messages API (ANTHROPIC_API_KEY)
  3. Google Gemini (GOOGLE_API_KEY / NOSTRADAMUS_GOOGLE_API_KEY)
  4. Rule-based fallback in research_controller.hypothesize_rules

Set RESEARCH_LLM_DISABLED=1 to skip LLM entirely.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

RESEARCH_DIR = REPO / "data" / "intelligence" / "research"
REASONING_PATH = RESEARCH_DIR / "reasoning.jsonl"

ALLOWED_TYPES = frozenset({
    "alpha_neutralization",
    "alpha_tweak",
    "genome_search",
    "genome_concentration",
    "concentration_fix",
    "feature_add",
    "sleeve_expand",
    "sleeve_decay",
    "promotion_gate",
    "raw_edge_check",
})

ALLOWED_ROUTES = frozenset({
    "walkforward_engine",
    "mad_scientist",
    "observe_only",
    "act_only",
})

POLICY_VIOLATION_PATTERNS = (
    re.compile(r"\brespawn\b.*\bv[12]\b", re.I),
    re.compile(r"\bv[12]\b.*\brespawn\b", re.I),
    re.compile(r"\bmodify\b.*\bv[12]\b.*\bgenome", re.I),
    re.compile(r"\bweaken\b.*\breadiness\b", re.I),
    re.compile(r"\bbypass\b.*\b(gate|readiness)\b", re.I),
    re.compile(r"\blive[_\s]?trading\b.*\b(true|enable|open)\b", re.I),
    re.compile(r"\bdisable\b.*\b(paper|dry[_\s]?run)\b", re.I),
    re.compile(r"--respawn\b", re.I),
)

SYSTEM_PROMPT = """You are the scientific meta-controller for Nostradamus Treasure Droid — an autonomous quant research machine.

## North star
Forward paper Sharpe + tradeable quintile spread on liquid names is the ONLY scoreboard.
Arena sim and historical walk-forward are candidate generators — upper bounds, not proof.

## Fundamental Law (Grinold)
IR = IC × √Breadth × Transfer Coefficient. Optimize tradeable quintile spread (transfer), not raw IC trapped in microcaps/warrants.

## Your job
Given observation JSON, propose 1-4 FALSIFIABLE hypotheses testable via walkforward_engine or mad_scientist.

## Rules (mandatory)
1. Every hypothesis MUST state "If we X, then Y measurable metric will change because Z".
2. Pre-register successCriteria BEFORE the experiment (holdout_mean_quintile_spread_gt, holdout_mean_ic_gt, etc.).
3. Auto-reject Sharpe/ICIR without positive tradeable quintile spread — selection bias trap.
4. NEVER suggest respawning, rewriting, or modifying Investor Arena v1 or v2 (frozen baselines).
5. NEVER weaken readiness gate, bypass spread gate, or open live trading.
6. Flag selection bias when suggesting genome promotions from mad_scientist Sharpe alone.
7. promotion_gate hypotheses are observe_only when edge_proven=false.
8. concentration_fix / genome_search for symbol clustering — require walkforward spread confirm.

## Output format
Return ONLY a JSON array (no markdown fences). Each element:
{
  "type": "alpha_tweak|genome_search|concentration_fix|sleeve_expand|feature_add|...",
  "hypothesis": "If we ..., tradeable quintile spread will ... because ...",
  "successCriteria": {"holdout_mean_quintile_spread_gt": 0.0, ...},
  "experiment": {"route": "walkforward_engine|mad_scientist|observe_only|act_only", "params": {}},
  "priority": 1,
  "reasoning": "brief chain-of-thought citing observation numbers",
  "confidence": 0.0
}

priority: 1=highest, 5=lowest. Max 4 hypotheses. Skip duplicate blocked gates."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hypothesis_id(statement: str, htype: str) -> str:
    raw = f"{htype}|{statement[:120]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")


def llm_disabled() -> bool:
    flag = (os.getenv("RESEARCH_LLM_DISABLED") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _load_env() -> None:
    try:
        from app_secrets import load_secrets
        load_secrets()
    except Exception:
        pass
    try:
        from intelligence.megamind_secrets import load_into_env
        load_into_env()
    except Exception:
        pass


def _extract_json_array(text: str) -> list | None:
    text = (text or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def _http_post_json(url: str, body: dict, headers: dict, timeout: float = 60.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_openai(prompt: str, obs: dict) -> tuple[str | None, str]:
    key = (os.getenv("OPENAI_API_KEY") or os.getenv("NOSTRADAMUS_OPENAI_API_KEY") or "").strip()
    if not key:
        return None, "openai_skip"
    base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL") or os.getenv("RESEARCH_LLM_MODEL") or "gpt-4o-mini"
    body = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Observation JSON:\n{json.dumps(obs, indent=0)[:8000]}\n\nEmit hypotheses JSON array."},
        ],
    }
    try:
        data = _http_post_json(
            f"{base}/chat/completions",
            body,
            {"Authorization": f"Bearer {key}"},
        )
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return (text.strip() or None), f"openai:{model}"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"openai_error:{str(exc)[:120]}"


def _call_anthropic(prompt: str, obs: dict) -> tuple[str | None, str]:
    key = (os.getenv("ANTHROPIC_API_KEY") or os.getenv("NOSTRADAMUS_ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None, "anthropic_skip"
    model = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-20250514"
    body = {
        "model": model,
        "max_tokens": 2000,
        "temperature": 0.2,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": f"Observation JSON:\n{json.dumps(obs, indent=0)[:8000]}\n\nEmit hypotheses JSON array."},
        ],
    }
    try:
        data = _http_post_json(
            "https://api.anthropic.com/v1/messages",
            body,
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return (text.strip() or None), f"anthropic:{model}"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"anthropic_error:{str(exc)[:120]}"


def _call_gemini(obs: dict) -> tuple[str | None, str]:
    try:
        from npu_llm import generate_text
    except ImportError:
        return None, "gemini_skip"
    user = (
        f"{SYSTEM_PROMPT}\n\nObservation JSON:\n{json.dumps(obs, indent=0)[:8000]}\n\n"
        "Return ONLY the JSON array of hypotheses."
    )
    text = generate_text(user, max_tokens=2000)
    if text and text.strip().startswith("["):
        return text.strip(), "gemini"
    return None, "gemini_skip"


def call_llm(obs: dict) -> tuple[str | None, str]:
    """Try providers in order; return (raw_text, backend_label)."""
    if llm_disabled():
        return None, "disabled"
    _load_env()
    for fn in (_call_openai, _call_anthropic):
        text, backend = fn("", obs)
        if text:
            return text, backend
    text, backend = _call_gemini(obs)
    if text:
        return text, backend
    return None, backend


def policy_violation(text: str) -> str | None:
    blob = text or ""
    for pat in POLICY_VIOLATION_PATTERNS:
        m = pat.search(blob)
        if m:
            return m.group(0)
    return None


def _coerce_success_criteria(raw: dict | None) -> dict:
    criteria = dict(raw or {})
    if "min_holdout_spread" in criteria and "holdout_mean_quintile_spread_gt" not in criteria:
        criteria["holdout_mean_quintile_spread_gt"] = criteria.pop("min_holdout_spread")
    if "min_forward_ic_days" in criteria:
        criteria.setdefault("forward_ic_days_gte", criteria.pop("min_forward_ic_days"))
    return criteria


def normalize_hypothesis(raw: dict, obs: dict | None = None) -> dict | None:
    """Map LLM JSON to research_controller schema."""
    if not isinstance(raw, dict):
        return None

    htype = str(raw.get("type") or "").strip()
    if htype not in ALLOWED_TYPES:
        return None

    statement = (raw.get("hypothesis") or raw.get("statement") or "").strip()
    if len(statement) < 20:
        return None
    if not re.search(r"\b(if|when|will|because)\b", statement, re.I):
        return None

    exp = raw.get("experiment") or {}
    route = str(exp.get("route") or raw.get("route") or "").strip()
    if route not in ALLOWED_ROUTES:
        return None

    params = dict(exp.get("params") or raw.get("params") or {})
    reasoning = str(raw.get("reasoning") or raw.get("rationale") or "").strip()
    blob = json.dumps(raw, default=str)
    viol = policy_violation(blob)
    if viol:
        return None

    if htype == "promotion_gate" and obs and not obs.get("edgeProven"):
        route = "observe_only"
        params = {}

    criteria = _coerce_success_criteria(raw.get("successCriteria"))
    if route in ("walkforward_engine", "mad_scientist"):
        criteria.setdefault("holdout_mean_quintile_spread_gt", 0.0)
        criteria.setdefault("reject_if_sharpe_high_spread_negative", True)

    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    try:
        priority = int(raw.get("priority", 3))
    except (TypeError, ValueError):
        priority = 3
    priority = max(1, min(5, priority))

    return {
        "id": _hypothesis_id(statement, htype),
        "type": htype,
        "statement": statement,
        "rationale": reasoning or f"LLM hypothesis ({htype})",
        "successCriteria": criteria,
        "route": route,
        "params": params,
        "status": "blocked" if route == "observe_only" and htype == "promotion_gate" else "pending",
        "preRegisteredAt": _now(),
        "source": "llm",
        "reasoning": reasoning,
        "confidence": confidence,
        "priority": priority,
    }


def filter_and_normalize(raw_list: list, obs: dict) -> tuple[list[dict], list[str]]:
    """Validate LLM output; return (hypotheses, rejection_reasons)."""
    out: list[dict] = []
    rejections: list[str] = []
    seen: set[str] = set()

    for i, raw in enumerate(raw_list or []):
        norm = normalize_hypothesis(raw, obs)
        if norm is None:
            rejections.append(f"item_{i}:invalid_or_policy")
            continue
        if norm["id"] in seen:
            rejections.append(f"item_{i}:duplicate")
            continue
        seen.add(norm["id"])
        out.append(norm)

    out.sort(key=lambda h: (h.get("priority", 3), -h.get("confidence", 0)))
    return out[:4], rejections


def reason(obs: dict, *, mock_response: str | None = None) -> tuple[list[dict], dict]:
    """Generate hypotheses via LLM; return (hypotheses, meta). Empty list => use rules fallback."""
    meta: dict = {"at": _now(), "backend": "rules_fallback", "ok": False}

    if llm_disabled() and mock_response is None:
        meta["reason"] = "RESEARCH_LLM_DISABLED"
        return [], meta

    raw_text: str | None
    backend: str
    if mock_response is not None:
        raw_text, backend = mock_response, "mock"
    else:
        raw_text, backend = call_llm(obs)

    meta["backend"] = backend

    if not raw_text:
        meta["reason"] = "no_llm_response"
        return [], meta

    parsed = _extract_json_array(raw_text)
    if not parsed:
        meta["reason"] = "json_parse_failed"
        meta["rawPreview"] = raw_text[:500]
        return [], meta

    hyps, rejections = filter_and_normalize(parsed, obs)
    meta["ok"] = bool(hyps)
    meta["nParsed"] = len(parsed)
    meta["nAccepted"] = len(hyps)
    meta["rejections"] = rejections
    meta["rawPreview"] = raw_text[:800]

    log_row = {**meta, "observedAt": obs.get("observedAt"), "hypothesisIds": [h["id"] for h in hyps]}
    _append_jsonl(REASONING_PATH, log_row)

    return hyps, meta


def enqueue_megamind_proposal(hyp: dict, decision: dict, *, dry_run: bool = True) -> dict:
    """Optionally queue a Megamind recommendation for human approve (never auto-approve)."""
    if decision.get("verdict") != "accept":
        return {"queued": False, "reason": "not_accepted"}

    area_map = {
        "genome_search": "concentration_risk",
        "genome_concentration": "concentration_risk",
        "concentration_fix": "concentration_risk",
        "alpha_neutralization": "alpha_factory",
        "alpha_tweak": "alpha_factory",
        "feature_add": "data_pipelines",
        "sleeve_expand": "arena_expansion",
    }
    area = area_map.get(hyp.get("type") or "", "research_controller")
    rec = {
        "priority": "medium",
        "area": area,
        "finding": hyp.get("statement", "")[:240],
        "action": (
            f"Research controller accepted hypothesis {hyp.get('id')}: "
            f"implement via {hyp.get('route')} with evidence {decision.get('reasons')}"
        ),
        "detail": json.dumps(decision.get("evidence") or {}, default=str)[:500],
        "researchHypothesisId": hyp.get("id"),
        "source": "research_controller",
    }

    if dry_run:
        return {"queued": False, "dryRun": True, "proposal": rec}

    try:
        from intelligence.megamind import _merge_recommendations, rec_id
        rid = rec_id(rec)
        rec["id"] = rid
        _merge_recommendations([rec])
        return {"queued": True, "recommendationId": rid, "dryRun": False}
    except Exception as exc:
        return {"queued": False, "error": str(exc)[:200]}
