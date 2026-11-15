"""Request-body and query-param bounds (audit SEC-06).

Each case is something that previously reached the database or an upstream
API unchecked: an over-long name is a 500 on Postgres (String(200)), a
free-text directions origin is a billed geocode, an unbounded saved_plan is
free storage.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import rate_limit as rl  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.models.trip import Leg, Stop, Trip  # noqa: E402
from app.models.venue import Venue  # noqa: E402
from app.schemas import MAX_STOPS_PER_REQUEST, ReviewDecisionIn  # noqa: E402
from app.schemas_account import AccountUpdate  # noqa: E402
from app.schemas_itinerary import MAX_SAVED_PLAN_BYTES, MAX_TAGS, ItineraryCreate, ItineraryUpdate  # noqa: E402


class _NoLimitRedis:
    def incr(self, key):
        return 1

    def expire(self, key, ttl):
        pass


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Venue.__table__, Trip.__table__, Stop.__table__, Leg.__table__])
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(rl, "get_redis", lambda: _NoLimitRedis())
    with patch("app.main._wait_for_db", return_value=None):
        from app.main import app

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()


def _trip(client):
    trip = client.post("/api/trips", json={"name": "T"}).json()
    return trip["id"], {"X-Trip-Token": trip["access_token"]}


# ── Trips / stops / legs ─────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["", "x" * 201])
def test_trip_name_length_is_bounded(client, name):
    assert client.post("/api/trips", json={"name": name}).status_code == 422


@pytest.mark.parametrize("stop", [
    {"name": "x" * 201, "lat": 34.0, "lng": -118.0},
    {"name": "", "lat": 34.0, "lng": -118.0},
    {"name": "Ok", "lat": 90.5, "lng": -118.0},
    {"name": "Ok", "lat": 34.0, "lng": -180.5},
])
def test_stop_fields_are_bounded(client, stop):
    trip_id, auth = _trip(client)
    assert client.post(f"/api/trips/{trip_id}/stops", json=stop, headers=auth).status_code == 422


def test_valid_stop_at_the_bounds_is_accepted(client):
    trip_id, auth = _trip(client)
    resp = client.post(
        f"/api/trips/{trip_id}/stops", json={"name": "x" * 200, "lat": -90, "lng": 180}, headers=auth,
    )
    assert resp.status_code == 201


def test_reorder_list_is_bounded(client):
    trip_id, auth = _trip(client)
    body = [{"stop_id": i, "order_index": i} for i in range(MAX_STOPS_PER_REQUEST + 1)]
    assert client.patch(f"/api/trips/{trip_id}/stops/reorder", json=body, headers=auth).status_code == 422


@pytest.mark.parametrize("leg", [
    {"mode": "x" * 21},
    {"mode": "walking", "distance_m": -1},
    {"mode": "walking", "polyline": "p" * 200_001},
])
def test_leg_fields_are_bounded(client, leg):
    trip_id, auth = _trip(client)
    body = {"from_stop_id": 1, "to_stop_id": 2, **leg}
    assert client.put(f"/api/trips/{trip_id}/legs", json=body, headers=auth).status_code == 422


# ── Directions: coordinates only ─────────────────────────────────────────────

@pytest.mark.parametrize("origin", ["Union Station, Los Angeles", "34.05", "34.05,-118.24,7", "x" * 60, ""])
def test_directions_rejects_non_coordinate_origin(client, origin):
    with patch("app.routers.directions.fetch_directions") as fetch:
        resp = client.get("/api/directions", params={"origin": origin, "destination": "34.06,-118.25"})
    assert resp.status_code == 422
    fetch.assert_not_called()  # never reaches Google


@pytest.mark.parametrize("origin", ["34.05,-118.24", "34.0522, -118.2437", "-33.9,151.2", "34,-118"])
def test_directions_accepts_coordinates(client, origin):
    result = {"mode": "walking", "distance_m": 1, "duration_s": 1, "polyline": "", "steps": []}
    with patch("app.routers.directions.fetch_directions", return_value=result):
        resp = client.get(
            "/api/directions", params={"origin": origin, "destination": "34.06,-118.25", "mode": "walking"},
        )
    assert resp.status_code == 200


def test_directions_language_is_bounded(client):
    resp = client.get(
        "/api/directions",
        params={"origin": "34.05,-118.24", "destination": "34.06,-118.25", "language": "x" * 11},
    )
    assert resp.status_code == 422


# ── Route optimize ───────────────────────────────────────────────────────────

_OD = {"origin": {"lat": 34.05, "lng": -118.24}, "destination": {"lat": 34.06, "lng": -118.25}}


@pytest.mark.parametrize("extra", [
    {"preferences": ["transit"] * 13},
    {"preferences": ["m" * 21]},
    {"departure_time": -1},
    {"departure_time": 10**12},
    {"language": "x" * 11},
    {"origin": {"lat": 91, "lng": 0}},
])
def test_optimize_request_is_bounded(client, extra):
    with patch("app.routers.routes.route_engine.optimize") as optimize:
        resp = client.post("/api/routes/optimize", json={**_OD, **extra})
    assert resp.status_code == 422
    optimize.assert_not_called()


def test_transit_live_line_is_bounded(client):
    assert client.get("/api/transit/live", params={"line": "x" * 101}).status_code == 422


# ── Itineraries / account / review (schema level — these routes need auth) ───

def test_itinerary_tags_are_bounded():
    with pytest.raises(ValidationError):
        ItineraryCreate(name="n", tags=["t" * 51])
    with pytest.raises(ValidationError):
        ItineraryCreate(name="n", tags=[f"t{i}" for i in range(MAX_TAGS + 1)])
    with pytest.raises(ValidationError):
        ItineraryUpdate(tags=["t" * 51])
    assert ItineraryCreate(name="n", tags=["t" * 50] * MAX_TAGS).tags


def test_saved_plan_size_is_bounded():
    big = {"blob": "x" * (MAX_SAVED_PLAN_BYTES + 1)}
    with pytest.raises(ValidationError):
        ItineraryCreate(name="n", saved_plan=big)
    with pytest.raises(ValidationError):
        ItineraryUpdate(saved_plan=big)
    realistic = {"stops": [{"name": "SoFi", "lat": 33.95, "lng": -118.34}] * 10, "legs": {"0-1": {"p": "x" * 50_000}}}
    assert ItineraryCreate(name="n", saved_plan=realistic).saved_plan == realistic
    assert ItineraryUpdate(saved_plan=None).saved_plan is None


def test_default_modes_must_be_known_route_modes():
    assert AccountUpdate(default_modes=["transit", "walk", "ridehail"]).default_modes
    with pytest.raises(ValidationError):
        AccountUpdate(default_modes=["teleport"])
    with pytest.raises(ValidationError):
        AccountUpdate(default_modes=["walk"] * 13)


def test_review_decision_must_be_a_known_value():
    assert ReviewDecisionIn(decision="approve").decision == "approve"
    with pytest.raises(ValidationError):
        ReviewDecisionIn(decision="rubber-stamp")
    with pytest.raises(ValidationError):
        ReviewDecisionIn(decision="reject", reviewed_by="r" * 101)
