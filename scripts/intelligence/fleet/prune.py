"""Fleet-wide kill loop — retire dead forward-paper agents.

Applies to ALL non-retired agents (genomes included), not just mad-scientist
spawns. Marks ``status: retired`` with a reason. Does not delete agent files
or ledgers. Never touches Investor Arena v1/v2 genomes or ledgers.

Honor-roll ids are spared only while their forward return is still positive;
negative honor-roll still dies.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AGENTS_DIR = REPO / "data" / "fleet" / "agents"

MIN_FORWARD_DAYS = 20
KILL_RETURN_PCT = 0.0

# Named survivors. Empty until a human puts an id here. Positive return only
# — a name on this list with negative forward return still retires.
HONOR_ROLL = frozenset()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _equity_stats(agent_id: str) -> tuple[int, float | None]:
    """Return (n_forward_days, return_pct) from the agent's equity curve."""
    eq = _load(AGENTS_DIR / agent_id / "equity.json", [])
    if not isinstance(eq, list) or not eq:
        today = _load(AGENTS_DIR / agent_id / "today.json", {})
        ret = today.get("returnPct")
        n = 1 if today.get("date") else 0
        return n, (float(ret) if ret is not None else None)
    n = len(eq)
    start = float((eq[0] or {}).get("equity") or 0)
    end = float((eq[-1] or {}).get("equity") or 0)
    if start <= 0:
        today = _load(AGENTS_DIR / agent_id / "today.json", {})
        ret = today.get("returnPct")
        return n, (float(ret) if ret is not None else None)
    return n, (end / start - 1.0) * 100.0


def _ledger_kills() -> set[str]:
    try:
        from intelligence.edge_ledger import killed_ids
        return killed_ids("fleet")
    except Exception as exc:  # noqa: BLE001
        print(f"[prune] edge ledger unread: {exc}", flush=True)
        return set()


def prune() -> dict:
    """Retire agents that lost on a 20-day forward book or were ledger-killed."""
    from intelligence.fleet import registry

    reg = registry.load_registry()
    ledger_kills = _ledger_kills()
    retired: list[dict] = []
    skipped_honor = []
    skipped_arena = 0

    for agent in reg.get("agents") or []:
        aid = str(agent.get("id") or "")
        if not aid:
            continue
        status = str(agent.get("status") or "").lower()
        if status == "retired":
            continue
        # Belt: never interpret arena v1/v2 trader ids as fleet agents.
        if aid.startswith("arena_v1_") or aid.startswith("arena_v2_"):
            skipped_arena += 1
            continue

        n_days, ret_pct = _equity_stats(aid)
        ledger_kill = aid in ledger_kills or f"fleet:{aid}" in ledger_kills

        if ledger_kill:
            agent["status"] = "retired"
            agent["retiredAt"] = _now()
            agent["retireReason"] = "edge_ledger_kill"
            retired.append({"id": aid, "reason": "edge_ledger_kill", "nDays": n_days, "returnPct": ret_pct})
            print(f"[prune] retire {aid} — edge ledger verdict=kill", flush=True)
            continue

        if n_days < MIN_FORWARD_DAYS:
            continue
        if ret_pct is None or ret_pct >= KILL_RETURN_PCT:
            continue

        if aid in HONOR_ROLL and ret_pct > 0:
            skipped_honor.append(aid)
            continue

        agent["status"] = "retired"
        agent["retiredAt"] = _now()
        agent["retireReason"] = (
            f"forward_return {ret_pct:.3f}% < {KILL_RETURN_PCT} over {n_days} days"
        )
        retired.append({
            "id": aid,
            "kind": agent.get("kind"),
            "reason": agent["retireReason"],
            "nDays": n_days,
            "returnPct": ret_pct,
        })
        print(f"[prune] retire {aid} ({agent.get('kind')}) {agent['retireReason']}", flush=True)

    if retired:
        registry.save_registry(reg)

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "minForwardDays": MIN_FORWARD_DAYS,
        "killReturnPct": KILL_RETURN_PCT,
        "nRetired": len(retired),
        "retired": retired,
        "honorRollSpared": skipped_honor,
        "arenaSkipped": skipped_arena,
        "note": "Agent files and ledgers kept. Arena v1/v2 untouched.",
    }
    out = REPO / "data" / "fleet" / "prune.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[prune] retired={len(retired)} honor_spared={len(skipped_honor)}", flush=True)
    return doc


if __name__ == "__main__":
    print(json.dumps(prune(), indent=2))
