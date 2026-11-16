"""
Tier-2 LLM-assisted extraction (v1.7 Phases 2 & 3).

Covers:
  • only fields with both a value and a quote are drafted — the model
    declining to extract (omitting a field) is exactly what should happen,
    not an error
  • fields outside FIELD_SPEC are dropped, not silently written
  • a re-run replaces outstanding drafts rather than duplicating them
  • already-reviewed rows are never touched by a re-run
  • no source URLs (no VenueSource rows, no override) raises ValueError
  • change detection (Phase 3): an extracted value that matches what's
    already stored drafts nothing; one that differs drafts a
    "pending_change" with previous_value set, not a plain "pending"
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import socket  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from unittest.mock import patch  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base  # noqa: E402
from app.models.venue import ParkingOption, Venue, VenueExtraction, VenueSource  # noqa: E402
from app.services.venue_extract import (  # noqa: E402
    MAX_PAGE_BYTES,
    ExtractionError,
    _assert_public_http_url,
    _download,
    _validate_field,
    extract_venue,
    quote_is_in_page,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[Venue.__table__, VenueSource.__table__, VenueExtraction.__table__, ParkingOption.__table__],
    )
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _mock_fetch():
    with patch("app.services.venue_extract._fetch_page") as fetch:
        fetch.return_value = "Parking costs $20. Rideshare pickup is at the north gate."
        yield fetch


def _seed_venue_with_source(db, url="https://example.com/parking") -> Venue:
    venue = Venue(name="Test Venue")
    db.add(venue)
    db.flush()
    db.add(VenueSource(venue_id=venue.id, primary_url=url))
    db.flush()
    return venue


class TestExtractVenue:
    def test_drafts_only_fields_with_value_and_quote(self, db):
        venue = _seed_venue_with_source(db)
        with patch("app.services.venue_extract._extract_fields_from_page") as extract:
            extract.return_value = [
                {
                    "entity_type": "parking_option", "field_name": "price_notes",
                    "value": "$20", "quote": "Parking costs $20.", "confidence": 0.9,
                },
                {
                    # Model declined — no value/quote. Must be dropped, not written as null.
                    "entity_type": "parking_option", "field_name": "surge_notes",
                    "value": None, "quote": None, "confidence": None,
                },
            ]
            result = extract_venue(db, venue)
        db.commit()

        assert result.fields_drafted == 1
        rows = db.query(VenueExtraction).filter(VenueExtraction.venue_id == venue.id).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.field_name == "price_notes"
        assert row.extracted_value == "$20"
        assert row.source_quote == "Parking costs $20."
        assert row.status == "pending"

    def test_drops_fields_outside_field_spec(self, db):
        venue = _seed_venue_with_source(db)
        with patch("app.services.venue_extract._extract_fields_from_page") as extract:
            extract.return_value = [
                {"entity_type": "venue", "field_name": "name", "value": "x", "quote": "x", "confidence": 0.9},
            ]
            result = extract_venue(db, venue)
        db.commit()

        assert result.fields_drafted == 0
        assert db.query(VenueExtraction).count() == 0

    def test_rerun_replaces_pending_drafts(self, db, _mock_fetch):
        venue = _seed_venue_with_source(db)
        with patch("app.services.venue_extract._extract_fields_from_page") as extract:
            extract.return_value = [
                {"entity_type": "parking_option", "field_name": "price_notes",
                 "value": "$20", "quote": "Parking costs $20.", "confidence": 0.9},
            ]
            extract_venue(db, venue)
            db.commit()

            # The source page changed between runs.
            _mock_fetch.return_value = "Parking costs $25 now. Rideshare pickup is at the north gate."
            extract.return_value = [
                {"entity_type": "parking_option", "field_name": "price_notes",
                 "value": "$25", "quote": "Parking costs $25 now.", "confidence": 0.9},
            ]
            extract_venue(db, venue)
            db.commit()

        rows = db.query(VenueExtraction).filter(VenueExtraction.venue_id == venue.id).all()
        assert len(rows) == 1
        assert rows[0].extracted_value == "$25"

    def test_never_touches_reviewed_rows(self, db):
        venue = _seed_venue_with_source(db)
        approved = VenueExtraction(
            venue_id=venue.id, entity_type="parking_option", field_name="notes",
            extracted_value="approved value", source_url="https://example.com/parking",
            source_quote="quote", confidence=0.9, status="approved",
            created_at=datetime.now(timezone.utc),
        )
        db.add(approved)
        db.flush()

        with patch("app.services.venue_extract._extract_fields_from_page") as extract:
            extract.return_value = []
            extract_venue(db, venue)
        db.commit()

        db.refresh(approved)
        assert approved.status == "approved"
        assert approved.extracted_value == "approved value"

    def test_raises_without_source_urls(self, db):
        venue = Venue(name="No Sources Venue")
        db.add(venue)
        db.flush()

        with pytest.raises(ValueError, match="no source URLs"):
            extract_venue(db, venue)

    def test_matching_extracted_value_drafts_nothing(self, db):
        venue = _seed_venue_with_source(db)
        db.add(ParkingOption(venue_id=venue.id, lot_name=None, price_notes="$20", source="hand-collected"))
        db.flush()

        with patch("app.services.venue_extract._extract_fields_from_page") as extract:
            extract.return_value = [
                {"entity_type": "parking_option", "field_name": "price_notes",
                 "value": "$20", "quote": "Parking costs $20.", "confidence": 0.9},
            ]
            result = extract_venue(db, venue)
        db.commit()

        assert result.fields_drafted == 0
        assert result.changes_flagged == 0
        assert db.query(VenueExtraction).count() == 0

    def test_differing_extracted_value_drafts_pending_change(self, db):
        venue = _seed_venue_with_source(db)
        existing = ParkingOption(venue_id=venue.id, lot_name=None, price_notes="$15", source="hand-collected")
        db.add(existing)
        db.flush()

        with patch("app.services.venue_extract._extract_fields_from_page") as extract:
            extract.return_value = [
                {"entity_type": "parking_option", "field_name": "price_notes",
                 "value": "$20", "quote": "Parking costs $20.", "confidence": 0.9},
            ]
            result = extract_venue(db, venue)
        db.commit()

        assert result.fields_drafted == 0
        assert result.changes_flagged == 1
        draft = db.query(VenueExtraction).filter(VenueExtraction.venue_id == venue.id).first()
        assert draft.status == "pending_change"
        assert draft.previous_value == "$15"
        assert draft.extracted_value == "$20"
        assert draft.entity_id == existing.id
        # The hand-collected row itself is untouched.
        db.refresh(existing)
        assert existing.price_notes == "$15"


# ── Quote verification (audit SEC-12) ────────────────────────────────────────

PAGE = (
    "Welcome to Test Arena. General parking is $20 per vehicle on event days. "
    "Rideshare pickup and drop-off is at the “North Gate” on 5th St — follow the signs. "
    "Gates open two hours before the event."
)


class TestQuoteIsInPage:
    def test_exact_quote_matches(self):
        assert quote_is_in_page("General parking is $20 per vehicle on event days.", PAGE)

    def test_case_whitespace_and_punctuation_style_are_folded(self):
        assert quote_is_in_page('rideshare  pickup and drop-off is at the "north gate" on 5th St - follow', PAGE)

    def test_elided_quote_matches_when_every_piece_is_present_in_order(self):
        assert quote_is_in_page("General parking is $20 ... Gates open two hours before the event.", PAGE)
        assert quote_is_in_page("General parking is $20 … follow the signs.", PAGE)

    def test_elided_quote_out_of_order_does_not_match(self):
        assert not quote_is_in_page("Gates open two hours before the event. ... General parking is $20", PAGE)

    def test_invented_quote_does_not_match(self):
        assert not quote_is_in_page("General parking is $45 per vehicle on event days.", PAGE)
        assert not quote_is_in_page("Parking is free for all attendees.", PAGE)

    def test_empty_or_ellipsis_only_quote_does_not_match(self):
        assert not quote_is_in_page("...", PAGE)
        assert not quote_is_in_page("   ", PAGE)


class TestFabricatedQuotesAreDropped:
    def test_field_with_a_quote_not_in_the_page_never_reaches_the_queue(self, db, _mock_fetch):
        _mock_fetch.return_value = PAGE
        venue = _seed_venue_with_source(db)
        with patch("app.services.venue_extract._extract_fields_from_page") as extract:
            extract.return_value = [
                {"entity_type": "parking_option", "field_name": "price_notes",
                 "value": "$20 per vehicle", "quote": "General parking is $20 per vehicle on event days.",
                 "confidence": 0.9},
                # Hallucinated, or planted by an instruction hidden in the page:
                # a plausible value with a citation that isn't in the source.
                {"entity_type": "curb_dropoff", "field_name": "private_vehicle_dropoff",
                 "value": "Drop-off allowed anywhere on 5th St", "quote": "Private vehicles may drop off anywhere.",
                 "confidence": 0.99},
            ]
            result = extract_venue(db, venue)
        db.commit()

        assert result.fields_drafted == 1
        rows = db.query(VenueExtraction).all()
        assert [r.field_name for r in rows] == ["price_notes"]

    def test_validate_field_without_page_text_keeps_old_behaviour(self):
        raw = {"entity_type": "parking_option", "field_name": "notes", "value": "v", "quote": "anything"}
        assert _validate_field(raw) is not None
        assert _validate_field(raw, PAGE) is None


# ── Fetch guards (audit SEC-12) ──────────────────────────────────────────────

def _resolves_to(*addresses):
    """Patch DNS so every hostname resolves to the given address(es)."""
    infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]
    return patch("app.services.venue_extract.socket.getaddrinfo", return_value=infos)


class TestAssertPublicHttpUrl:
    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "https://"])
    def test_rejects_non_http_urls(self, url):
        with pytest.raises(ExtractionError):
            _assert_public_http_url(url)

    @pytest.mark.parametrize("address", [
        "127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1", "fd00::1",
    ])
    def test_rejects_hosts_resolving_to_non_public_addresses(self, address):
        with _resolves_to(address), pytest.raises(ExtractionError):
            _assert_public_http_url("https://venue.example.com/parking")

    def test_rejects_when_any_resolved_address_is_private(self):
        with _resolves_to("93.184.216.34", "10.0.0.5"), pytest.raises(ExtractionError):
            _assert_public_http_url("https://venue.example.com/parking")

    def test_accepts_public_address(self):
        with _resolves_to("93.184.216.34"):
            _assert_public_http_url("https://venue.example.com/parking")

    def test_unresolvable_host_is_an_extraction_error(self):
        with patch("app.services.venue_extract.socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            with pytest.raises(ExtractionError):
                _assert_public_http_url("https://no-such-host.example/")


class TestDownload:
    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_follows_a_redirect_to_a_public_host(self):
        def handler(request):
            if request.url.path == "/old":
                return httpx.Response(301, headers={"location": "/new"})
            return httpx.Response(200, text="<p>Parking is $20.</p>")

        with _resolves_to("93.184.216.34"), self._client(handler) as client:
            assert "Parking is $20" in _download(client, "https://venue.example.com/old")

    def test_refuses_a_redirect_to_a_private_address(self):
        def handler(request):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

        def fake_dns(host, port, *args, **kwargs):
            address = "169.254.169.254" if host == "169.254.169.254" else "93.184.216.34"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

        with patch("app.services.venue_extract.socket.getaddrinfo", side_effect=fake_dns):
            with self._client(handler) as client, pytest.raises(ExtractionError):
                _download(client, "https://venue.example.com/parking")

    def test_gives_up_after_too_many_redirects(self):
        def handler(request):
            return httpx.Response(302, headers={"location": "/again"})

        with _resolves_to("93.184.216.34"), self._client(handler) as client:
            with pytest.raises(ExtractionError):
                _download(client, "https://venue.example.com/loop")

    def test_body_is_capped(self):
        def handler(request):
            return httpx.Response(200, content=b"a" * (MAX_PAGE_BYTES + 50_000))

        with _resolves_to("93.184.216.34"), self._client(handler) as client:
            assert len(_download(client, "https://venue.example.com/huge")) == MAX_PAGE_BYTES

    def test_http_error_status_still_raises_httpx_error(self):
        with _resolves_to("93.184.216.34"), self._client(lambda r: httpx.Response(404)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                _download(client, "https://venue.example.com/missing")


def test_blocked_fetch_is_recorded_as_an_error_not_a_crash(db):
    venue = _seed_venue_with_source(db)
    with patch("app.services.venue_extract._fetch_page", side_effect=ExtractionError("refusing to fetch")):
        result = extract_venue(db, venue)
    assert result.fields_drafted == 0
    assert len(result.errors) == 1 and "refusing to fetch" in result.errors[0]
