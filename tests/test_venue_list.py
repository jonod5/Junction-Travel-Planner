"""GET /api/venues — list endpoint for the map/picker (not per-venue detail)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.models.venue import Venue  # noqa: E402


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
