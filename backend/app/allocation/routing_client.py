import logging
import time

import httpx

from app.core.config import settings

log = logging.getLogger("crisisgrid.routing")

_client = httpx.Client(timeout=httpx.Timeout(3.0, connect=1.0),
                       limits=httpx.Limits(max_connections=50))
_down_until = 0.0
COOLDOWN_S = 20.0


def travel_times(sources: list[tuple[float, float]], dest: tuple[float, float]):
    """sources and dest are (lon, lat). Returns (durations_s, distances_m), or None if OSRM
    is unavailable (the caller then falls back to straight-line estimates)."""
    global _down_until
    if time.monotonic() < _down_until:
        return None                      # OSRM failed recently; do not wait on it again yet

    coords = ";".join(f"{lon},{lat}" for lon, lat in sources + [dest])
    src_idx = ";".join(str(i) for i in range(len(sources)))
    dst_idx = str(len(sources))
    url = f"{settings.osrm_url}/table/v1/driving/{coords}"
    try:
        r = _client.get(url, params={"sources": src_idx, "destinations": dst_idx,
                                     "annotations": "duration,distance"})
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            log.warning("OSRM returned code %s", data.get("code"))
            return None
        durations = [row[0] for row in data["durations"]]
        distances = [row[0] for row in data["distances"]]
        return durations, distances
    except Exception as exc:             # any routing failure must degrade, never crash dispatch
        _down_until = time.monotonic() + COOLDOWN_S
        log.warning("OSRM unavailable, using fallback for %ss: %r", COOLDOWN_S, exc)
        return None