"""GET /api/places — Google Places proxy: trimming, caching, rate limit (audit SEC-04)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import rate_limit as rl  # noqa: E402
from app.routers import places  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, ttl):
        pass


GOOGLE_OK = {
    "status": "OK",
    "results": [
        {"name": "Union Station", "formatted_address": "800 N Alameda St", "place_id": "SECRET", "geometry": {}},
    ],
}


def _upstream(payload=GOOGLE_OK):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.__enter__.return_value.get.return_value = resp
    return client


@pytest.fixture
def client(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(places, "get_redis", lambda: fake)
    monkeypatch.setattr(rl, "get_redis", lambda: fake)
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    with patch("app.main._wait_for_db", return_value=None):
        from app.main import app
        with TestClient(app) as c:
            c.fake_redis = fake
            yield c


def test_returns_only_name_and_address(client):
    with patch.object(places.httpx, "Client", return_value=_upstream()):
        body = client.get("/api/places", params={"query": "union station"}).json()
    assert body["results"] == [{"name": "Union Station", "address": "800 N Alameda St"}]
    assert "SECRET" not in str(body)


def test_second_identical_query_is_served_from_cache(client):
    upstream = _upstream()
    with patch.object(places.httpx, "Client", return_value=upstream) as ctor:
        first = client.get("/api/places", params={"query": "Union Station"}).json()
        second = client.get("/api/places", params={"query": "  union   STATION "}).json()
    assert ctor.call_count == 1  # normalized query → one billed call
    assert first["results"] == second["results"]


def test_cache_failure_falls_through_to_the_api(client, monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(places, "get_redis", broken)
    with patch.object(places.httpx, "Client", return_value=_upstream()):
        resp = client.get("/api/places", params={"query": "union station"})
    assert resp.status_code == 200


def test_has_its_own_per_client_rate_limit(client, monkeypatch):
    monkeypatch.setattr(places, "get_redis", lambda: FakeRedis())  # no cache hits
    with patch.object(places.httpx, "Client", return_value=_upstream()):
        codes = [
            client.get("/api/places", params={"query": f"q{i}"}).status_code
            for i in range(places.PLACES_RATE_LIMIT + 1)
        ]
    assert codes[:-1] == [200] * places.PLACES_RATE_LIMIT
    assert codes[-1] == 429


def test_missing_key_is_a_500_without_calling_google(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_KEY", raising=False)
    with patch.object(places.httpx, "Client") as ctor:
        resp = client.get("/api/places", params={"query": "anything"})
    assert resp.status_code == 500
    ctor.assert_not_called()


def test_query_length_is_bounded(client):
    assert client.get("/api/places", params={"query": "x" * 201}).status_code == 422
    assert client.get("/api/places", params={"query": ""}).status_code == 422


def test_older_key_name_is_honoured_too(client, monkeypatch):
    # Audit MESS-01: places only read GOOGLE_MAPS_API_KEY while directions and
    # geocoding also accepted GOOGLE_MAPS_KEY. All three share one accessor now.
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_MAPS_KEY", "legacy-name")
    upstream = _upstream()
    with patch.object(places.httpx, "Client", return_value=upstream):
        assert client.get("/api/places", params={"query": "union station"}).status_code == 200
    assert upstream.__enter__.return_value.get.call_args.kwargs["params"]["key"] == "legacy-name"
