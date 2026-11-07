import json
import logging
from datetime import datetime, timezone

import redis

from app.core.config import settings

log = logging.getLogger("crisisgrid.events")

CHANNEL = "crisisgrid:events"
_r = redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)


def publish(event_type: str, data: dict) -> None:
    """Fire-and-forget. A Redis outage must never break dispatching."""
    try:
        _r.publish(CHANNEL, json.dumps({
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }, default=str))
    except Exception as exc:
        log.warning("Could not publish %s: %r", event_type, exc)