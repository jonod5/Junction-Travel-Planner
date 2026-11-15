"""
Server-side Google Geocoding proxy — used only by app/register_venues.py to
turn a venue name into coordinates. Same backend-proxy pattern as
app/routers/places.py and app/services/directions.py: the key never leaves
the server.

Precision matters here more than for a one-off Places search — Tier-1
enrichment is only as good as the coordinate it's given a radius around, so
every result carries Google's own `location_type` verbatim, and
confidence_label() maps it to the same "high"/"medium"/"low" vocabulary
Venue.confidence already uses elsewhere in the pipeline. Callers (not this
module) decide what to do with a low-confidence result — this module never
silently upgrades or hides one.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from app.cache import get_redis

log = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
# Venue locations don't move — cache aggressively, unlike Directions' 1h TTL.
CACHE_TTL_S = 30 * 24 * 3600

# Google's location_type values, worst to best:
#   ROOFTOP             — precise to the specific building/address
#   RANGE_INTERPOLATED   — interpolated between two points on a road
#   GEOMETRIC_CENTER     — center of a line/polygon (a park, a beach, a road)
#   APPROXIMATE          — a rough area (city, region)
_CONFIDENCE_BY_LOCATION_TYPE = {
    "ROOFTOP": "high",
    "RANGE_INTERPOLATED": "medium",
    "GEOMETRIC_CENTER": "low",
    "APPROXIMATE": "low",
}


class GeocodeError(Exception):
    """Config failure, upstream failure, or ZERO_RESULTS — never invents a coordinate."""


def _api_key() -> str | None:
    return os.environ.get("GOOGLE_MAPS_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY")


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    location_type: str
    formatted_address: str

    @property
    def confidence(self) -> str:
        return _CONFIDENCE_BY_LOCATION_TYPE.get(self.location_type, "low")


def geocode_address(query: str) -> GeocodeResult:
    """Geocode a free-text address/place query. Raises GeocodeError on any
    failure — config, upstream, or no results — never returns a guess."""
    api_key = _api_key()
    if not api_key:
        raise GeocodeError("Maps API key not configured")

    r = get_redis()
    key = f"geocode:{query.strip().lower()}"
    cached = r.get(key)
    if cached is not None:
        lat, lng, location_type, formatted_address = cached.split("\x1f")
        return GeocodeResult(float(lat), float(lng), location_type, formatted_address)

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(GEOCODE_URL, params={"address": query, "key": api_key})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise GeocodeError(f"Geocoding request failed for {query!r}: {exc}") from exc

    status = data.get("status")
    if status != "OK":
        raise GeocodeError(f"Geocoding failed for {query!r}: {status} — {data.get('error_message', '')}".strip())

    top = data["results"][0]
    location = top["geometry"]["location"]
    result = GeocodeResult(
        lat=location["lat"],
        lng=location["lng"],
        location_type=top["geometry"].get("location_type", "APPROXIMATE"),
        formatted_address=top.get("formatted_address", query),
    )
    r.setex(
        key, CACHE_TTL_S,
        f"{result.lat}\x1f{result.lng}\x1f{result.location_type}\x1f{result.formatted_address}",
    )
    return result
