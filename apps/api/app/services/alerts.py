"""Alerts (plan §17.5): webhook (Slack/Telegram-compatible JSON) on 3 consecutive job failures, model down,
disk > threshold and publish failure. Debounced so a flapping check does not spam."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

import httpx

from app.core.config import get_settings

log = logging.getLogger("app.alerts")
_last_sent: dict[str, float] = {}
DEBOUNCE_S = 1800


async def send(kind: str, text: str, *, force: bool = False) -> bool:
    s = get_settings()
    now = time.monotonic()
    if not force and now - _last_sent.get(kind, -DEBOUNCE_S * 2) < DEBOUNCE_S:
        return False
    _last_sent[kind] = now
    log.warning("ALERT %s: %s", kind, text)
    if not s.alert_webhook_url:
        return False
    body = {"text": f"[LayerFlow] {text}", "content": f"[LayerFlow] {text}", "kind": kind}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(s.alert_webhook_url, json=body)
        return True
    except httpx.HTTPError as exc:
        log.error("alert webhook failed: %s", exc)
        return False


def disk_usage(path: Path | None = None) -> dict[str, float]:
    target = Path(path or get_settings().artifacts_dir)
    probe = target
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return {
        "total_gb": round(usage.total / 1e9, 1),
        "free_gb": round(usage.free / 1e9, 1),
        "used_pct": round((usage.used / usage.total) * 100, 1) if usage.total else 0.0,
    }
