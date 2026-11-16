"""
GET /api/directions — server-side proxy to Google Directions API.

Thin HTTP layer: validates the query, applies the per-client rate limit, and
maps the client's errors to status codes. The Directions client itself —
fetching, caching, step parsing — lives in app/services/directions.py, where
the route engine and venue enrichment use it too.

- A 502 (not 500) is returned when Google is unreachable — the client is the
  upstream from the browser's perspective, and 502 is semantically correct for
  a bad gateway response.
- ZERO_RESULTS (no route found) returns 404 with a clear message rather than
  an empty 200, so the frontend can show a useful error state.
"""

import logging
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query

from app.rate_limit import DIRECTIONS_RATE_LIMIT, rate_limit
from app.services.directions import DirectionsError, fetch_directions

log = logging.getLogger(__name__)
router = APIRouter(tags=["directions"])


class TravelMode(StrEnum):
    driving = "driving"
    transit = "transit"
    walking = "walking"
    bicycling = "bicycling"


# The public endpoint takes coordinates only. Google would happily geocode a
# free-text place name here, which costs more per call and gives every
# distinct string its own cache entry. (Internal callers of fetch_directions
# always pass coordinates already.)
_LATLNG_PATTERN = r"^\s*-?\d{1,2}(\.\d+)?\s*,\s*-?\d{1,3}(\.\d+)?\s*$"


@router.get("/api/directions", dependencies=[Depends(rate_limit("directions", DIRECTIONS_RATE_LIMIT, 60))])
def get_directions(
    origin: str = Query(..., pattern=_LATLNG_PATTERN, max_length=50, description="lat,lng of the start point"),
    destination: str = Query(..., pattern=_LATLNG_PATTERN, max_length=50, description="lat,lng of the end point"),
    mode: TravelMode = Query(TravelMode.transit, description="Travel mode"),
    language: str | None = Query(
        None, max_length=10, description="App locale code (en/es/fr/zh-Hans); unsupported falls back to en",
    ),
):
    """
    Proxy Google Directions and return trimmed routing data.

    Rate-limited (see app.rate_limit) — this calls the real, paid Google
    Directions API on a cache miss, so an unbounded client could otherwise
    drive up billing directly through our own proxy.

    Returns: {mode, distance_m, duration_s, polyline, steps}
    Caches results in Redis for 1 hour, keyed per language too.
    """
    try:
        result = fetch_directions(origin, destination, str(mode), language=language)
    except DirectionsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {mode} route found between the given points",
        )
    return result
