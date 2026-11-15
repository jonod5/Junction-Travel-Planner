"""
Trip/stop CRUD — /api/trips. No dedicated coverage existed for this router
before; added alongside the stops/reorder deadlock-ordering fix (see
app/routers/trips.py's reorder_stops) so that fix has a regression test
and this router isn't entirely untested going forward.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.models.trip import Leg, Stop, Trip  # noqa: E402
from app.models.venue import Venue  # noqa: E402


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Venue.__table__, Trip.__table__, Stop.__table__, Leg.__table__])
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    with patch.dict(os.environ, {"DATABASE_URL": "sqlite://"}), patch(
        "app.main._wait_for_db", return_value=None
    ):
        from app.main import app

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()


def _make_trip_with_stops(client, n=3):
    """Returns (trip_id, stop_ids, auth) — auth is the X-Trip-Token header
    every non-create trip route requires."""
    trip = client.post("/api/trips", json={"name": "Test Trip"}).json()
    auth = {"X-Trip-Token": trip["access_token"]}
    stop_ids = []
    for i in range(n):
        resp = client.post(
            f"/api/trips/{trip['id']}/stops",
            json={"name": f"Stop {i}", "lat": 34.0 + i, "lng": -118.0 - i},
            headers=auth,
        )
        stop_ids.append(resp.json()["id"])
    return trip["id"], stop_ids, auth


def test_create_trip(client):
    resp = client.post("/api/trips", json={"name": "My Trip"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "My Trip"


def test_add_stop(client):
    trip_id, _, auth = _make_trip_with_stops(client, n=1)
    resp = client.get(f"/api/trips/{trip_id}", headers=auth)
    assert len(resp.json()["stops"]) == 1


def test_reorder_stops_applies_requested_order(client):
    trip_id, stop_ids, auth = _make_trip_with_stops(client, n=3)
    # Reverse the order, sent in an arbitrary (non-sorted-by-stop_id) sequence.
    body = [
        {"stop_id": stop_ids[2], "order_index": 0},
        {"stop_id": stop_ids[0], "order_index": 2},
        {"stop_id": stop_ids[1], "order_index": 1},
    ]
    resp = client.patch(f"/api/trips/{trip_id}/stops/reorder", json=body, headers=auth)
    assert resp.status_code == 200
    stops = sorted(resp.json()["stops"], key=lambda s: s["order_index"])
    assert [s["id"] for s in stops] == [stop_ids[2], stop_ids[1], stop_ids[0]]


def test_reorder_stops_ignores_unknown_stop_ids(client):
    trip_id, stop_ids, auth = _make_trip_with_stops(client, n=2)
    resp = client.patch(
        f"/api/trips/{trip_id}/stops/reorder",
        json=[{"stop_id": 999999, "order_index": 5}, {"stop_id": stop_ids[0], "order_index": 1}],
        headers=auth,
    )
    assert resp.status_code == 200


def test_reorder_stops_unknown_trip_404(client):
    resp = client.patch("/api/trips/999999/stops/reorder", json=[])
    assert resp.status_code == 404


def test_delete_stop(client):
    trip_id, stop_ids, auth = _make_trip_with_stops(client, n=2)
    resp = client.delete(f"/api/trips/{trip_id}/stops/{stop_ids[0]}", headers=auth)
    assert resp.status_code == 204
    remaining = client.get(f"/api/trips/{trip_id}", headers=auth).json()["stops"]
    assert len(remaining) == 1


# ── Access control (audit SEC-02) ────────────────────────────────────────────
# Trips are anonymous, so there's no owner to scope by: the token returned by
# POST /api/trips is the only thing that grants access to a trip.

def _all_trip_requests(trip_id, stop_ids):
    """Every non-create trip route, as (method, url, json-or-None)."""
    return [
        ("GET", f"/api/trips/{trip_id}", None),
        ("PATCH", f"/api/trips/{trip_id}", {"name": "Hijacked"}),
        ("POST", f"/api/trips/{trip_id}/stops", {"name": "Injected", "lat": 34.0, "lng": -118.0}),
        ("PATCH", f"/api/trips/{trip_id}/stops/reorder", [{"stop_id": stop_ids[0], "order_index": 9}]),
        ("PUT", f"/api/trips/{trip_id}/legs",
         {"from_stop_id": stop_ids[0], "to_stop_id": stop_ids[1], "mode": "walking"}),
        ("DELETE", f"/api/trips/{trip_id}/stops/{stop_ids[0]}", None),
        ("DELETE", f"/api/trips/{trip_id}", None),
    ]


def test_create_returns_a_token_and_other_routes_never_do(client):
    created = client.post("/api/trips", json={"name": "My Trip"}).json()
    assert len(created["access_token"]) >= 32
    fetched = client.get(f"/api/trips/{created['id']}", headers={"X-Trip-Token": created["access_token"]})
    assert fetched.status_code == 200
    assert "access_token" not in fetched.json()


def test_each_trip_gets_its_own_token(client):
    a = client.post("/api/trips", json={"name": "A"}).json()
    b = client.post("/api/trips", json={"name": "B"}).json()
    assert a["access_token"] != b["access_token"]


@pytest.mark.parametrize("headers", [{}, {"X-Trip-Token": ""}, {"X-Trip-Token": "not-the-token"}])
def test_every_route_is_404_without_the_right_token(client, headers):
    trip_id, stop_ids, auth = _make_trip_with_stops(client, n=2)
    for method, url, body in _all_trip_requests(trip_id, stop_ids):
        resp = client.request(method, url, json=body, headers=headers)
        assert resp.status_code == 404, f"{method} {url} -> {resp.status_code}"
    # Nothing was changed or deleted by any of those attempts.
    trip = client.get(f"/api/trips/{trip_id}", headers=auth).json()
    assert trip["name"] == "Test Trip"
    assert [s["id"] for s in trip["stops"]] == stop_ids


def test_another_trips_token_does_not_work(client):
    trip_a, stops_a, _auth_a = _make_trip_with_stops(client, n=2)
    _trip_b, _stops_b, auth_b = _make_trip_with_stops(client, n=2)
    for method, url, body in _all_trip_requests(trip_a, stops_a):
        resp = client.request(method, url, json=body, headers=auth_b)
        assert resp.status_code == 404, f"{method} {url} -> {resp.status_code}"


def test_wrong_token_looks_the_same_as_a_missing_trip(client):
    trip_id, _, _ = _make_trip_with_stops(client, n=1)
    wrong = client.get(f"/api/trips/{trip_id}", headers={"X-Trip-Token": "nope"})
    missing = client.get("/api/trips/999999", headers={"X-Trip-Token": "nope"})
    assert wrong.status_code == missing.status_code == 404
    assert wrong.json()["detail"].replace(str(trip_id), "N") == missing.json()["detail"].replace("999999", "N")


def test_trip_without_a_token_is_unreachable(client):
    """Rows created before migration 0018 have access_token NULL."""
    db = next(client.app.dependency_overrides[get_db]())
    legacy = Trip(name="Legacy")
    db.add(legacy)
    db.commit()
    legacy_id = legacy.id
    db.close()
    for headers in ({}, {"X-Trip-Token": ""}, {"X-Trip-Token": "None"}):
        assert client.get(f"/api/trips/{legacy_id}", headers=headers).status_code == 404


def test_client_supplied_user_id_is_ignored(client):
    created = client.post("/api/trips", json={"name": "T", "user_id": "someone-else"}).json()
    assert created["user_id"] is None


def test_leg_cannot_reference_another_trips_stops(client):
    trip_a, stops_a, auth_a = _make_trip_with_stops(client, n=2)
    _trip_b, stops_b, _ = _make_trip_with_stops(client, n=2)
    resp = client.put(
        f"/api/trips/{trip_a}/legs",
        json={"from_stop_id": stops_a[0], "to_stop_id": stops_b[0], "mode": "walking"},
        headers=auth_a,
    )
    assert resp.status_code == 404
    ok = client.put(
        f"/api/trips/{trip_a}/legs",
        json={"from_stop_id": stops_a[0], "to_stop_id": stops_a[1], "mode": "walking"},
        headers=auth_a,
    )
    assert ok.status_code == 201
