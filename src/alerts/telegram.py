"""Telegram alerting for high-severity signals (spec Phase 2).

Configured via environment variables so bot tokens never land in YAML:
    TELEGRAM_BOT_TOKEN   — the bot's HTTP API token
    TELEGRAM_CHAT_ID     — the chat or channel to notify
    TELEGRAM_MIN_SEVERITY — optional override (default: 4)

When either of the first two is missing, alerting is silently disabled so
local dev runs keep working.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

import httpx

from src.models import Signal

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
DEFAULT_MIN_SEVERITY = 4
MAX_MESSAGE_LEN = 3500  # Telegram hard-limits at 4096; leave headroom for formatting.


class TelegramAlerter:
    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        min_severity: int | None = None,
        timeout: float = 10.0,
    ):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        env_sev = os.environ.get("TELEGRAM_MIN_SEVERITY")
        if min_severity is not None:
            self.min_severity = min_severity
        elif env_sev and env_sev.isdigit():
            self.min_severity = int(env_sev)
        else:
            self.min_severity = DEFAULT_MIN_SEVERITY
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_signal(self, signal: Signal) -> bool:
        if not self.enabled:
            return False
        if signal.severity < self.min_severity:
            return False
        return self._send(_format_signal(signal))

    def send_signals(self, signals: Iterable[Signal]) -> int:
        if not self.enabled:
            return 0
        sent = 0
        for sig in signals:
            if self.send_signal(sig):
                sent += 1
        return sent

    def _send(self, text: str) -> bool:
        if len(text) > MAX_MESSAGE_LEN:
            text = text[:MAX_MESSAGE_LEN] + "…"
        url = TELEGRAM_API.format(token=self.bot_token)
        try:
            resp = httpx.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.warning("Telegram alert failed: %s", e)
            return False


def _format_signal(signal: Signal) -> str:
    sev_icon = "🚨" if signal.severity >= 5 else "⚠️"
    lines = [
        f"{sev_icon} <b>[{signal.severity}] {_escape(signal.competitor_id)}</b>",
        f"<i>{_escape(signal.source)} / {_escape(signal.signal_type)}</i>",
        "",
        _escape(signal.title),
    ]
    if signal.content and signal.content != signal.title:
        lines.append("")
        lines.append(_escape(signal.content[:400]))
    if signal.url:
        lines.append("")
        lines.append(f'<a href="{_escape(signal.url)}">source</a>')
    return "\n".join(lines)


def _escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
