# ############################################################################
# AI_HEADER: telegram_notify
# ROLE: Telegram bot for GRACE Control Plane notifications.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Send Telegram notifications on key events (packet claimed, accepted, rejected, worker died).
# inputs: Event type + entity data.
# returns: None.
# side_effects: HTTP POST to Telegram API.
# emitted_logs: None.
# error_behavior: Silent on failure — notifications must never block operations.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: notify_event
#   - function: set_telegram_config
# END_MODULE_MAP

from __future__ import annotations

import os

import httpx

_token: str | None = None
_chat_id: str | None = None


def set_telegram_config(token: str | None = None, chat_id: str | None = None) -> None:
    global _token, _chat_id
    _token = token or os.environ.get("GRACE_TELEGRAM_TOKEN")
    _chat_id = chat_id or os.environ.get("GRACE_TELEGRAM_CHAT_ID")


async def notify_event(event_type: str, packet_id: str, **kwargs) -> None:
    if not _token or not _chat_id:
        return

    icons = {
        "packet_claimed": "📥",
        "packet_released": "📤",
        "packet_merged": "✅",
        "packet_cancelled": "❌",
    }
    emoji = icons.get(event_type, "ℹ️")
    details = " ".join(f"{k}={v}" for k, v in kwargs.items())

    text = f"{emoji} *{event_type}*\n`{packet_id}`\n{details}"[:4096]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{_token}/sendMessage",
                json={"chat_id": _chat_id, "text": text, "parse_mode": "Markdown"},
            )
    except Exception:
        pass
