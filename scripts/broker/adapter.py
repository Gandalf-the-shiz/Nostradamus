"""Broker abstraction — paper simulation today, Robinhood Agents tomorrow.

Robinhood Agents (external) should poll:
  GET /api/trading/manifest

and POST execution acknowledgements:
  POST /api/trading/ack

This module defines the canonical order schema both sides agree on.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
TRADING_DIR = REPO / "data" / "trading"
MANIFEST_PATH = TRADING_DIR / "robinhood_manifest.json"
PENDING_PATH = TRADING_DIR / "pending_orders.json"
EXEC_LOG_PATH = TRADING_DIR / "execution_log.jsonl"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class TradeIntent:
    """High-level signal from the investor agent."""
    symbol: str
    side: OrderSide
    notional_usd: float
    proba_up: float
    pred_ret: float
    edge: float
    rationale: str
    trade_date: str
    agent: str = "investor_v3"


@dataclass
class OrderRequest:
    """Broker-neutral order ready for execution."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float | None = None
    notional_usd: float | None = None
    limit_price: float | None = None
    time_in_force: str = "day"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["side"] = self.side.value
        d["order_type"] = self.order_type.value
        return d


@dataclass
class ExecutionReport:
    order_id: str
    status: str  # submitted | filled | rejected | cancelled
    filled_qty: float = 0.0
    filled_notional: float = 0.0
    avg_price: float | None = None
    message: str = ""
    broker: str = "paper"
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


class BrokerAdapter:
    """Base broker interface."""

    name: str = "base"

    def submit(self, order: OrderRequest) -> ExecutionReport:
        raise NotImplementedError

    def cancel(self, order_id: str) -> ExecutionReport:
        raise NotImplementedError


class PaperBroker(BrokerAdapter):
    """Simulated instant fill at last known close (preparation only)."""

    name = "paper"

    def submit(self, order: OrderRequest) -> ExecutionReport:
        notional = order.notional_usd or 0.0
        qty = order.quantity or (notional / max(order.limit_price or 1.0, 0.01))
        return ExecutionReport(
            order_id=order.order_id,
            status="filled",
            filled_qty=round(qty, 4),
            filled_notional=round(notional, 2),
            avg_price=order.limit_price,
            message="paper fill (simulated)",
            broker=self.name,
        )


class RobinhoodAgentBridge:
    """Export/import layer for Robinhood Agents external execution."""

    def __init__(self, mode: str | None = None) -> None:
        self.mode = (mode or os.getenv("BROKER_MODE", "paper")).strip().lower()
        self._paper = PaperBroker()

    @property
    def dry_run(self) -> bool:
        return self.mode in {"paper", "dry_run", "manifest_only"}

    def intents_to_orders(self, intents: list[TradeIntent], prices: dict[str, float]) -> list[OrderRequest]:
        orders: list[OrderRequest] = []
        for intent in intents:
            px = prices.get(intent.symbol.upper())
            if not px or px <= 0:
                continue
            qty = round(intent.notional_usd / px, 4)
            if qty <= 0:
                continue
            orders.append(
                OrderRequest(
                    order_id=str(uuid.uuid4()),
                    symbol=intent.symbol.upper(),
                    side=intent.side,
                    order_type=OrderType.MARKET,
                    quantity=qty,
                    notional_usd=round(intent.notional_usd, 2),
                    metadata={
                        "proba_up": intent.proba_up,
                        "pred_ret": intent.pred_ret,
                        "edge": intent.edge,
                        "rationale": intent.rationale,
                        "trade_date": intent.trade_date,
                        "agent": intent.agent,
                    },
                )
            )
        return orders

    def build_manifest(
        self,
        orders: list[OrderRequest],
        *,
        portfolio_value: float,
        cash_available: float,
        risk_notes: list[str] | None = None,
    ) -> dict:
        """Schema consumed by Robinhood Agents (or any external executor).

        Every manifest passes through the live-trading readiness gate, which
        forces dryRun/paper mode unless edge + forward PnL + risk + zero leakage
        flags are all green in the companion nostradamus-live repo.
        """
        manifest = {
            "schema": "nostradamus.trading.manifest/v1",
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": self.mode,
            "dryRun": self.dry_run,
            "brokerTarget": "robinhood_agents",
            "portfolio": {
                "valueUsd": portfolio_value,
                "cashAvailableUsd": cash_available,
            },
            "risk": {
                "maxGrossExposure": float(os.getenv("BROKER_MAX_GROSS_EXPOSURE", "0.90")),
                "maxPositionFrac": float(os.getenv("BROKER_MAX_POSITION_FRAC", "0.20")),
                "minProba": float(os.getenv("BROKER_MIN_PROBA", "0.60")),
                "notes": risk_notes or [],
            },
            "orders": [o.to_dict() for o in orders],
            "instructions": (
                "Execute orders in order. POST fills to /api/trading/ack with order_id and status."
            ),
        }
        return self._apply_live_gate(manifest)

    @staticmethod
    def _apply_live_gate(manifest: dict) -> dict:
        """Force paper mode unless the readiness gate permits live trading."""
        try:
            import sys
            scripts_dir = str(Path(__file__).resolve().parent.parent)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            import live_gate
            return live_gate.enforce(manifest)
        except Exception:
            # Fail-safe: any error in the gate path forces paper mode.
            manifest["dryRun"] = True
            manifest["mode"] = "paper"
            manifest.setdefault("risk", {}).setdefault("notes", []).append(
                "LIVE TRADING BLOCKED: readiness gate unavailable (fail-safe).")
            return manifest

    def write_manifest(self, manifest: dict) -> Path:
        TRADING_DIR.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        pending = {"orders": manifest.get("orders") or [], "updatedAt": manifest.get("generatedAt")}
        PENDING_PATH.write_text(json.dumps(pending, indent=2), encoding="utf-8")
        return MANIFEST_PATH

    def submit(self, order: OrderRequest) -> ExecutionReport:
        if self.dry_run:
            return self._paper.submit(order)
        # Live Robinhood: external agent executes from manifest; record as submitted.
        return ExecutionReport(
            order_id=order.order_id,
            status="submitted",
            message="queued for Robinhood Agents (external execution)",
            broker="robinhood_agents",
        )

    def record_ack(self, report: ExecutionReport) -> None:
        TRADING_DIR.mkdir(parents=True, exist_ok=True)
        with open(EXEC_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(report)) + "\n")
