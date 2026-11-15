"""
GET /api/places?query=  — server-side proxy to Google Places Text Search.

Design choices:
- The Google Maps key lives exclusively in the server environment; the client
  never sees it.
- We return only (name, address) — the minimum the frontend needs for
  autocomplete / display.  This reduces payload size and avoids leaking
  internal Place IDs that clients could use to bypass the proxy.
- httpx is used synchronously here; swap to AsyncClient + async def if the
  rest of the app goes async.
- Every upstream call is billed, so the route has its own strict per-client
  rate limit (like /api/directions) and a short Redis cache per normalized
  query. The cache fails open: a Redis problem costs an upstream call, it
  never fails the request.
"""

import hashlib
import json
import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.cache import get_redis
from app.rate_limit import rate_limit

log = logging.getLogger(__name__)
router = APIRouter()

PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
CACHE_TTL = 300  # 5 minutes — place search results for a given text are stable
PLACES_RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PLACES_PER_MIN", "10"))


def _cache_key(query: str) -> str:
    normalized = " ".join(query.lower().split())
    return "places:" + hashlib.md5(normalized.encode()).hexdigest()  # noqa: S324 — not crypto


def _cache_get(key: str) -> dict | None:
    try:
        cached = get_redis().get(key)
    except Exception:  # noqa: BLE001 — cache is best-effort
        log.warning("Places cache read failed — falling through to the API")
        return None
    return json.loads(cached) if cached else None


def _cache_set(key: str, value: dict) -> None:
    try:
        get_redis().setex(key, CACHE_TTL, json.dumps(value))
    except Exception:  # noqa: BLE001 — cache is best-effort
        log.warning("Places cache write failed")


@router.get("/api/places", dependencies=[Depends(rate_limit("places", PLACES_RATE_LIMIT, 60))])
def search_places(
    query: str = Query(
        ..., min_length=1, max_length=200, description="Free-text search query"
    ),
):
    """
    Proxy Google Places Text Search and return trimmed results.
    The GOOGLE_MAPS_KEY env var is injected server-side; clients never see it.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Maps API key not configured")

    cache_key = _cache_key(query)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    params = {
        "query": query,
        "key": api_key,
        # Bias results toward the LA region; does not restrict to it.
        "location": "34.0522,-118.2437",
        "radius": 50_000,
    }

    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(PLACES_URL, params=params)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.exception("Places API request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Places API unavailable") from exc

    data = resp.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        log.error("Places API error status: %s", data.get("status"))
        raise HTTPException(
            status_code=502, detail=f"Places API error: {data.get('status')}"
        )

    # Return only name + formatted_address — never pass raw Place data to
    # clients because it may contain billing-sensitive fields.
    results = [
        {
            "name": r.get("name"),
            "address": r.get("formatted_address"),
        }
        for r in data.get("results", [])
    ]

    payload = {"query": query, "count": len(results), "results": results}
    _cache_set(cache_key, payload)
    return payload
