"""app.register_venues — geocode + minimal venue registration (v1.7)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base  # noqa: E402
from app.models.venue import Venue  # noqa: E402
from app.services.geocode import GeocodeError, GeocodeResult  # noqa: E402
from app.register_venues import register_venue  # noqa: E402

SPEC = dict(
    external_ref="intuit-dome", name="Intuit Dome", zone="Inglewood", sport_use="Basketball",
    geocode_query="Intuit Dome, Inglewood, CA",
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Venue.__table__])
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def _result(lat=33.9457, lng=-118.3416, location_type="ROOFTOP") -> GeocodeResult:
    return GeocodeResult(lat=lat, lng=lng, location_type=location_type, formatted_address="Some Address, CA")


class TestRegisterVenue:
    def test_registers_new_venue_with_provenance(self, db):
        with patch("app.register_venues.geocode_address", return_value=_result()):
            outcome = register_venue(db, SPEC)
        db.commit()

        assert outcome.status == "registered"
        assert outcome.needs_review is False
        venue = db.get(Venue, outcome.venue_id)
        assert venue.external_ref == "intuit-dome"
        assert venue.source == "geocoded"
        assert venue.confidence == "high"
        assert venue.reviewed is False  # Tier-1 enrichment hasn't run yet
        assert float(venue.lat) == pytest.approx(33.9457)

    def test_non_rooftop_result_flagged_for_review(self, db):
        with patch("app.register_venues.geocode_address", return_value=_result(location_type="APPROXIMATE")):
            outcome = register_venue(db, SPEC)

        assert outcome.status == "registered"
        assert outcome.needs_review is True

    def test_fuzzy_flag_forces_review_even_if_rooftop(self, db):
        spec = {**SPEC, "fuzzy": True}
        with patch("app.register_venues.geocode_address", return_value=_result(location_type="ROOFTOP")):
            outcome = register_venue(db, spec)

        assert outcome.needs_review is True

    def test_skips_when_external_ref_already_registered(self, db):
        db.add(Venue(name="Intuit Dome", external_ref="intuit-dome", lat=33.9, lng=-118.3))
        db.commit()

        with patch("app.register_venues.geocode_address") as geocode:
            outcome = register_venue(db, SPEC)

        geocode.assert_not_called()
        assert outcome.status == "skipped_existing"

    def test_skips_when_name_matches_existing_hand_collected_venue(self, db):
        # Hand-collected venues have external_ref=None — name match must
        # still catch them so this never creates a duplicate of one of the
        # original 6.
        db.add(Venue(name="LA Memorial Coliseum", external_ref=None, lat=34.0141, lng=-118.2879))
        db.commit()

        spec = {**SPEC, "external_ref": "la-memorial-coliseum", "name": "LA Memorial Coliseum"}
        with patch("app.register_venues.geocode_address") as geocode:
            outcome = register_venue(db, spec)

        geocode.assert_not_called()
        assert outcome.status == "skipped_existing"

    def test_skips_when_geocode_lands_near_a_hand_collected_venue(self, db):
        db.add(Venue(name="Some Hand-Collected Venue", external_ref=None, lat=33.9457, lng=-118.3416))
        db.commit()

        # ~50m away — within DEDUPE_RADIUS_M.
        with patch("app.register_venues.geocode_address", return_value=_result(lat=33.9461, lng=-118.3416)):
            outcome = register_venue(db, SPEC)

        assert outcome.status == "skipped_duplicate"
        assert db.query(Venue).count() == 1

    def test_does_not_dedupe_against_a_far_away_hand_collected_venue(self, db):
        db.add(Venue(name="Some Hand-Collected Venue", external_ref=None, lat=33.8, lng=-118.2))
        db.commit()

        with patch("app.register_venues.geocode_address", return_value=_result()):
            outcome = register_venue(db, SPEC)

        assert outcome.status == "registered"

    def test_does_not_dedupe_against_another_pipeline_registered_venue(self, db):
        # Two logically distinct venues (e.g. Carson Field / Carson Stadium)
        # that both resolve to the exact same parent-complex coordinate —
        # must NOT collapse into one row just because they're 0m apart, and
        # this must hold whether they're registered in the same run or a
        # later one (proximity dedup only ever matches a hand-collected
        # venue — see _find_by_proximity's docstring).
        db.add(Venue(
            name="Carson Stadium", external_ref="carson-stadium", lat=_result().lat, lng=_result().lng,
        ))
        db.commit()

        field_spec = {**SPEC, "external_ref": "carson-field", "name": "Carson Field"}
        with patch("app.register_venues.geocode_address", return_value=_result()):
            outcome = register_venue(db, field_spec)

        assert outcome.status == "registered"
        assert db.query(Venue).count() == 2

    def test_geocode_error_reported_not_raised(self, db):
        with patch("app.register_venues.geocode_address", side_effect=GeocodeError("ZERO_RESULTS")):
            outcome = register_venue(db, SPEC)

        assert outcome.status == "error"
        assert "ZERO_RESULTS" in outcome.detail
        assert db.query(Venue).count() == 0

    def test_manual_coordinate_override_skips_geocoding_entirely(self, db):
        spec = {**SPEC, "lat": 33.97657143605985, "lng": -118.46676819870399}
        with patch("app.register_venues.geocode_address") as geocode:
            outcome = register_venue(db, spec)
        db.commit()

        geocode.assert_not_called()
        assert outcome.status == "registered"
        assert outcome.needs_review is False
        venue = db.get(Venue, outcome.venue_id)
        assert float(venue.lat) == pytest.approx(33.97657143605985)
        assert venue.source == "user_verified"
        assert venue.confidence == "high"

    def test_manual_coordinate_override_still_goes_through_dedupe(self, db):
        db.add(Venue(name="Some Hand-Collected Venue", external_ref=None, lat=33.9457, lng=-118.3416))
        db.commit()

        spec = {**SPEC, "lat": 33.9459, "lng": -118.3416}  # ~20m from the hand-collected venue above
        outcome = register_venue(db, spec)

        assert outcome.status == "skipped_duplicate"


class TestListedFlag:
    """`listed` is set when a row is first created and never touched on a re-run."""

    HIDDEN = dict(SPEC, external_ref="honda-center", name="Honda Center", listed=False)

    def test_new_venue_defaults_to_listed(self, db):
        with patch("app.register_venues.geocode_address", return_value=_result()):
            outcome = register_venue(db, SPEC)
        db.commit()
        assert db.get(Venue, outcome.venue_id).listed is True

    def test_listed_false_spec_registers_hidden(self, db):
        with patch("app.register_venues.geocode_address", return_value=_result()):
            outcome = register_venue(db, self.HIDDEN)
        db.commit()
        assert db.get(Venue, outcome.venue_id).listed is False

    def test_rerun_does_not_flip_hidden_venue_back_to_listed(self, db):
        with patch("app.register_venues.geocode_address", return_value=_result()):
            first = register_venue(db, self.HIDDEN)
            db.commit()
            second = register_venue(db, self.HIDDEN)
            db.commit()
        assert second.status == "skipped_existing"
        assert db.get(Venue, first.venue_id).listed is False

    def test_rerun_with_a_spec_lacking_the_flag_leaves_a_hidden_row_hidden(self, db):
        # e.g. a row the 0017 migration hid, re-registered from a spec without listed=False
        db.add(Venue(name="Honda Center", external_ref="honda-center", lat=33.8, lng=-117.9, listed=False))
        db.commit()
        outcome = register_venue(db, dict(SPEC, external_ref="honda-center", name="Honda Center"))
        db.commit()
        assert outcome.status == "skipped_existing"
        assert db.get(Venue, outcome.venue_id).listed is False
