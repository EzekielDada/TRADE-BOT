"""Natural language control helpers for the dashboard."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

from config import Settings
from storage import Storage
from utils import safe_json_loads

try:
    from groq import Groq
except ImportError:  # pragma: no cover - optional dependency.
    Groq = None  # type: ignore[assignment]


CONTROL_PROMPT = """Parse this trading bot command and return ONLY JSON:
{
  "intent": str,
  "action": str,
  "parameters": dict,
  "requires_confirmation": bool,
  "confirmation_message": str
}
Command: {user_input}"""


@dataclass(slots=True)
class ControlResult:
    """Result of interpreting a dashboard command."""

    intent: str
    action: str
    parameters: dict[str, Any]
    requires_confirmation: bool
    confirmation_message: str
    message: str


class ControlInterpreter:
    """Interpret plain English commands into bot actions."""

    def __init__(self, settings: Settings, storage: Storage) -> None:
        """Create the interpreter."""

        self.settings = settings
        self.storage = storage
        self._client = Groq(api_key=settings.groq_api_key) if settings.groq_api_key and Groq else None

    def interpret(self, command: str) -> ControlResult:
        """Interpret a natural-language command."""

        logger.bind(command_log=True).info(f"Received command: {command}")
        if self._client:
            try:
                completion = self._client.chat.completions.create(
                    model=self.settings.groq_model,
                    temperature=0.0,
                    messages=[{"role": "user", "content": CONTROL_PROMPT.format(user_input=command)}],
                    response_format={"type": "json_object"},
                )
                payload = safe_json_loads(completion.choices[0].message.content or "{}")
                return self._from_payload(payload)
            except Exception as error:  # pragma: no cover - network dependent.
                logger.warning(f"Groq control parsing failed: {error}")
        return self._rule_based(command)

    def apply(self, result: ControlResult) -> None:
        """Persist approved control updates."""

        current = self.storage.get_state("runtime_overrides", {})
        current.update(result.parameters)
        self.storage.set_state("runtime_overrides", current)
        logger.bind(command_log=True).info(f"Applied command intent={result.intent} parameters={result.parameters}")

    def status_summary(self) -> dict[str, Any]:
        """Return a basic status summary for the dashboard."""

        return {
            "bot_paused": self.settings.bot_paused,
            "paper_trading": self.settings.paper_trading,
            "symbols": self.storage.get_state("selected_assets", self.settings.symbols),
            "last_signal": self.storage.fetch_signals(limit=1),
            "open_positions": self.storage.load_positions(),
            "briefing_complete": self.storage.get_state("briefing_complete", False),
            "last_report": self.storage.fetch_report("daily_briefing", self.storage.get_state("last_briefing_date", "")),
        }

    def _from_payload(self, payload: dict[str, Any]) -> ControlResult:
        """Normalize model output."""

        return ControlResult(
            intent=str(payload.get("intent", "unknown")),
            action=str(payload.get("action", payload.get("intent", "unknown"))),
            parameters=dict(payload.get("parameters", {})),
            requires_confirmation=bool(payload.get("requires_confirmation", False)),
            confirmation_message=str(payload.get("confirmation_message", "")),
            message=str(payload.get("confirmation_message", "Command interpreted.")),
        )

    def _rule_based(self, command: str) -> ControlResult:
        """Fallback rule-based parser when Groq is unavailable."""

        lower = command.lower()
        if "pause" in lower:
            return ControlResult("pause", "pause", {"bot_paused": True}, False, "", "Trading will be paused.")
        if "resume" in lower or "start" in lower:
            return ControlResult("resume", "resume", {"bot_paused": False}, False, "", "Trading will resume.")
        if "stop the bot" in lower:
            return ControlResult("stop", "stop", {"shutdown_requested": True}, True, "Are you sure you want to stop the bot gracefully?", "Shutdown requested.")
        if "paper" in lower:
            return ControlResult("switch_mode", "switch_mode", {"paper_trading": True}, False, "", "Paper trading mode enabled.")
        if "live" in lower:
            return ControlResult("switch_mode", "switch_mode", {"paper_trading": False}, True, "Are you sure? This enables real-money execution.", "Live trading mode requested.")
        if "only trade" in lower:
            matches = re.findall(r"\b[A-Z]{2,6}\b", command.upper())
            symbols = [f"{match}/USDT" for match in matches]
            return ControlResult("set_symbols", "set_symbols", {"symbols": symbols, "selected_assets": symbols}, False, "", f"Session symbols set to {symbols}.")
        if "risk" in lower:
            match = re.search(r"(\d+(?:\.\d+)?)\s*%", lower)
            if match:
                risk = float(match.group(1)) / 100
                return ControlResult("set_risk", "set_risk", {"risk_per_trade": risk}, True, "Are you sure? This increases risk.", f"Risk per trade will change to {risk:.2%}.")
        if "doing right now" in lower:
            return ControlResult("status", "status", {}, False, "", json.dumps(self.status_summary()))
        if "last trade" in lower or "why did the bot take the last trade" in lower:
            last_signal = self.storage.fetch_signals(limit=1)
            return ControlResult("last_trade_reason", "last_trade_reason", {}, False, "", json.dumps(last_signal[0] if last_signal else {}))
        if "this week" in lower:
            weekly_pnl = self.storage.get_state("weekly_realized_pnl", 0.0)
            return ControlResult("weekly_performance", "weekly_performance", {}, False, "", f"Weekly realized PnL: {weekly_pnl:.2f}")
        if "today's briefing" in lower or "todays briefing" in lower or "show me today's briefing" in lower:
            report = self.storage.fetch_report("daily_briefing", self.storage.get_state("last_briefing_date", ""))
            return ControlResult("show_briefing", "show_briefing", {}, False, "", json.dumps(report or {}))
        if "what patterns are active" in lower:
            active = self.storage.get_state("active_patterns", [])
            return ControlResult("active_patterns", "active_patterns", {}, False, "", json.dumps(active))
        return ControlResult("unknown", "unknown", {}, False, "", "Command was not recognized.")
