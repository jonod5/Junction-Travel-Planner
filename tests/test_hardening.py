"""Small hardening fixes from the November 2026 audit: API docs toggle
(SEC-14), upstream error details (SEC-15), survey session limit (SEC-19)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app import main  # noqa: E402
from app import rate_limit as rl  # noqa: E402
from app.routers import places, survey  # noqa: E402
from app.services import directions, route_engine  # noqa: E402


# ── SEC-14 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (None, True), ("true", True), ("1", True), ("anything", True),
    ("false", False), ("FALSE", False), ("0", False), ("no", False), (" off ", False),
])
def test_docs_toggle(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("API_DOCS_ENABLED", value)
    assert main._docs_enabled() is expected


# ── SEC-15 ───────────────────────────────────────────────────────────────────

class _Redis:
    def get(self, key):
        return None

    def setex(self, *args):
        pass


def _google(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.__enter__.return_value.get.return_value = resp
    return client


@pytest.mark.parametrize("status", ["REQUEST_DENIED", "OVER_QUERY_LIMIT", "INVALID_REQUEST", "UNKNOWN_ERROR"])
def test_directions_does_not_leak_upstream_status(monkeypatch, status):
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    monkeypatch.setattr(directions, "get_redis", lambda: _Redis())
    payload = {"status": status, "error_message": "The provided API key is invalid."}
    with patch.object(directions.httpx, "Client", return_value=_google(payload)):
        with pytest.raises(directions.DirectionsError) as exc:
            directions.fetch_directions("34.05,-118.24", "34.06,-118.25", "walking")
    assert exc.value.status_code == 502
    assert status not in exc.value.detail
    assert "key" not in exc.value.detail.lower()


def test_places_does_not_leak_upstream_status(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    monkeypatch.setattr(places, "get_redis", lambda: _Redis())
    with patch.object(places.httpx, "Client", return_value=_google({"status": "REQUEST_DENIED"})):
        with pytest.raises(HTTPException) as exc:
            places.search_places(query="union station")
    assert exc.value.status_code == 502
    assert "REQUEST_DENIED" not in exc.value.detail


def test_missing_maps_key_message_does_not_describe_configuration(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    with pytest.raises(directions.DirectionsError) as exc:
        directions.fetch_directions("34.05,-118.24", "34.06,-118.25", "walking")
    assert exc.value.status_code == 500 and "key" not in exc.value.detail.lower()
    with pytest.raises(directions.DirectionsError) as exc:
        route_engine.optimize((34.05, -118.24), (34.06, -118.25))
    assert exc.value.status_code == 500 and "key" not in exc.value.detail.lower()


# ── SEC-19 ───────────────────────────────────────────────────────────────────

def test_survey_session_start_has_its_own_rate_limit(monkeypatch):
    class Counter:
        def __init__(self):
            self.n: dict[str, int] = {}

        def incr(self, key):
            self.n[key] = self.n.get(key, 0) + 1
            return self.n[key]

        def expire(self, key, ttl):
            pass

    counter = Counter()
    monkeypatch.setattr(rl, "get_redis", lambda: counter)
    route = next(r for r in survey.router.routes if r.path == "/api/survey/{survey_id}/session")
    limiter = route.dependencies[0].dependency
    request = MagicMock()
    request.client.host = "203.0.113.5"
    for _ in range(survey.SESSION_RATE_LIMIT):
        limiter(request)
    with pytest.raises(HTTPException) as exc:
        limiter(request)
    assert exc.value.status_code == 429
    assert any(k.startswith("ratelimit:survey_session:") for k in counter.n)
