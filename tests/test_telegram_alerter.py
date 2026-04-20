from src.alerts.telegram import TelegramAlerter, _format_signal
from src.models import Signal


def test_alerter_disabled_without_env(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    alerter = TelegramAlerter()
    assert alerter.enabled is False
    assert alerter.send_signals([_sample_signal(5)]) == 0


def test_alerter_skips_low_severity(monkeypatch):
    alerter = TelegramAlerter(bot_token="t", chat_id="c", min_severity=4)
    calls: list[str] = []
    alerter._send = lambda text: calls.append(text) or True  # type: ignore[method-assign]
    alerter.send_signals([_sample_signal(2), _sample_signal(3), _sample_signal(5)])
    assert len(calls) == 1
    assert "[5]" in calls[0]


def test_format_escapes_html():
    sig = _sample_signal(5, title="<b>pwn</b>")
    text = _format_signal(sig)
    assert "<b>pwn</b>" not in text
    assert "&lt;b&gt;pwn&lt;/b&gt;" in text


def _sample_signal(sev: int, *, title: str = "t") -> Signal:
    return Signal(
        competitor_id="acme", source="news", signal_type="news_article",
        title=title, content="body", severity=sev,
    )
