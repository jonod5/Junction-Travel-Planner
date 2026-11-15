"""GET /api/venues — list endpoint for the map/picker (not per-venue detail)."""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.models.venue import (  # noqa: E402
    CongestionTdm,
    CurbDropoff,
    GamesTimeOfficial,
    ParkingOption,
    TransitAccess,
    Venue,
)
from app.register_venues import VENUES  # noqa: E402

# The 6 hand-collected venues (no external_ref) plus the 27 registered ones.
ORIGINAL_NAMES = ["Coliseum", "SoFi", "Dodger Stadium", "DTLA Arena", "Peacock Theater", "Rose Bowl"]


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Venue.__table__])
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    seed = TestSessionLocal()
    seed.add(Venue(id=1, name="Hand-Collected Venue", sport_use="Athletics", lat=34.0141, lng=-118.2879))
    seed.add(Venue(
        id=2, name="Registered Venue", external_ref="registered-venue", source="geocoded",
        lat=33.9438, lng=-118.3422,
    ))
    seed.add(Venue(id=3, name="No Coordinates Yet", lat=None, lng=None))
    seed.commit()
    seed.close()

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lists_every_venue_with_coordinates(client):
    resp = client.get("/api/venues")
    assert resp.status_code == 200
    names = [v["name"] for v in resp.json()]
    assert "Hand-Collected Venue" in names
    assert "Registered Venue" in names


def test_excludes_venues_without_coordinates(client):
    resp = client.get("/api/venues")
    names = [v["name"] for v in resp.json()]
    assert "No Coordinates Yet" not in names


def test_does_not_filter_by_reviewed_status(client):
    # A venue's own identity/location isn't gated by the "never show
    # unreviewed data as fact" rule — that's for parking/transit content.
    resp = client.get("/api/venues")
    ids = [v["id"] for v in resp.json()]
    assert 2 in ids  # "Registered Venue" defaults reviewed=False and still shows


# ── Metro-core scope: 15 listed, 18 hidden ──────────────────────────────────

_ALL_TABLES = [
    Venue.__table__, ParkingOption.__table__, CongestionTdm.__table__,
    TransitAccess.__table__, CurbDropoff.__table__, GamesTimeOfficial.__table__,
]


@pytest.fixture
def scoped_client():
    """The real venue set: 6 originals + every entry in register_venues.VENUES."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=_ALL_TABLES)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    seed = TestSessionLocal()
    for i, name in enumerate(ORIGINAL_NAMES, start=1):
        seed.add(Venue(id=i, name=name, lat=34.0 + i / 100, lng=-118.2))
    for j, spec in enumerate(VENUES, start=100):
        seed.add(Venue(
            id=j, name=spec["name"], external_ref=spec["external_ref"],
            lat=33.9 + j / 1000, lng=-118.3, listed=spec.get("listed", True),
        ))
    seed.commit()
    seed.close()

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _hidden_refs_in_registry() -> set[str]:
    return {v["external_ref"] for v in VENUES if v.get("listed") is False}


def test_list_returns_the_15_metro_core_venues_and_none_of_the_hidden_18(scoped_client):
    resp = scoped_client.get("/api/venues")
    assert resp.status_code == 200
    names = {v["name"] for v in resp.json()}
    hidden_names = {v["name"] for v in VENUES if v.get("listed") is False}

    assert len(resp.json()) == 15
    assert len(hidden_names) == 18
    assert names.isdisjoint(hidden_names)
    assert set(ORIGINAL_NAMES) <= names
    for needle in ("Honda", "Carson", "Long Beach"):
        assert not any(needle in n for n in names)


def test_migration_hides_exactly_the_registry_listed_false_venues():
    """alembic/versions/0017 and register_venues.py each carry the hidden list
    — guard against the two drifting apart."""
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0017_venue_listed.py"
    spec = importlib.util.spec_from_file_location("mig_0017", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.HIDDEN_REFS) == _hidden_refs_in_registry()
    assert len(mod.HIDDEN_REFS) == 18


def test_detail_endpoint_still_serves_a_hidden_venue(scoped_client):
    hidden = next(v for v in VENUES if v.get("listed") is False)
    hidden_id = 100 + VENUES.index(hidden)

    assert hidden["name"] not in {v["name"] for v in scoped_client.get("/api/venues").json()}
    resp = scoped_client.get(f"/api/venues/{hidden_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == hidden["name"]
