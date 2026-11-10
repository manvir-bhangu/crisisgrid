import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import redis

from app.core.config import settings

log = logging.getLogger("crisisgrid.events")

CHANNEL = "crisisgrid:events"
_r = redis.from_url(settings.redis_url, socket_connect_timeout=0.3, socket_timeout=0.5)
_pool = ThreadPoolExecutor(max_workers=1)    # a single worker keeps events in order
_down_until = 0.0
COOLDOWN_S = 10.0


def _send(message: str, event_type: str) -> None:
    global _down_until
    if time.monotonic() < _down_until:
        return
    try:
        _r.publish(CHANNEL, message)
    except Exception as exc:
        _down_until = time.monotonic() + COOLDOWN_S
        log.warning("Could not publish %s (pausing publishes for %ss): %r", event_type, COOLDOWN_S, exc)


def publish(event_type: str, data: dict) -> None:
    """Never blocks the caller. A Redis outage cannot slow down or break dispatching."""
    message = json.dumps({"type": event_type,
                          "ts": datetime.now(timezone.utc).isoformat(),
                          "data": data}, default=str)
    _pool.submit(_send, message, event_type)