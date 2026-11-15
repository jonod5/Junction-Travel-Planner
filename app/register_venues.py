"""
CLI to register new LA28 venues (geocode + minimal row) using the existing
v1.7 pipeline's registry model — see app/models/venue.py's "Registry"
section and app/services/geocode.py.

    python -m app.register_venues <external_ref> [<external_ref> ...]
    python -m app.register_venues --all

Registers only — geocodes, dedupes against existing venues, creates a
minimal Venue row (name/zone/sport_use/lat/lng), prints a summary table.
Does NOT run Tier-1 enrichment; that's a deliberate separate step (see
app/enrich_venue.py) so a human can eyeball low-confidence coordinates
before the pipeline builds transit data around them.

Idempotent: matches existing venues by external_ref first, then by
normalized name, then by proximity (≤150m) — but proximity dedup only ever
matches a HAND-COLLECTED venue (external_ref IS NULL), never another
pipeline-registered one. See _find_by_proximity()'s docstring for why:
several venues here genuinely share one parent complex's geocode and would
otherwise falsely collapse into a single row. Never touches the 6
hand-collected venues themselves, and never re-registers an
already-registered one (that's external_ref's job).

Confidence: every result is reported with Google's own location_type.
Anything other than ROOFTOP is flagged in the "needs review" list in the
summary — not hidden, not silently trusted — because Tier-1 enrichment
radius-searches around whatever coordinate it's given.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.ingest.gbfs import haversine_m
from app.models.venue import Venue
from app.services.geocode import GeocodeError, geocode_address

# ---------------------------------------------------------------------------
# Scope: the app lists only the LA Metro-served core. The venues tagged
# listed=False below are still registered (and still enriched/reviewed) but
# are hidden from GET /api/venues until their agency's GTFS feed is ingested
# — see docs/known-gaps.md. `listed` is applied only when a row is first
# created; re-running registration skips an existing venue entirely, so it
# never flips a hidden venue back to visible (or the reverse).
#
# LA28 venues (Greater LA region; football + OKC excluded; existing 6
# excluded) — per the LA28 Games Map, which is subject to change; noted in
# each row's data_sources_summary.
#
# geocode_query is hand-tuned per venue rather than a mechanical
# "name, zone, CA" concat — several of these (beaches, basins, temporary
# structures) don't geocode well from their official event name alone.
# ---------------------------------------------------------------------------

VENUES: list[dict] = [
    dict(external_ref="la-convention-center", name="LA Convention Center (Halls 1-3)", zone="DTLA",
         sport_use="Fencing, Judo, Table Tennis, Taekwondo, Wrestling",
         geocode_query="Los Angeles Convention Center, Los Angeles, CA"),
    # "Exposition Park Stadium" (flag football, lacrosse) is NOT a separate
    # venue — confirmed by user review of the geocoded coordinate — it's the
    # same physical structure as the existing hand-collected LA Memorial
    # Coliseum (venue id 1). Deliberately not registered here at all: the
    # Coliseum is one of the 6 hand-collected venues and this script must
    # never create a second row for it, even under a different LA28 event
    # name.
    dict(external_ref="galen-center", name="Galen Center", zone="Exposition Park",
         sport_use="Badminton, Rhythmic Gymnastics",
         geocode_query="Galen Center, Los Angeles, CA"),
    dict(external_ref="intuit-dome", name="Intuit Dome", zone="Inglewood", sport_use="Basketball",
         geocode_query="Intuit Dome, Inglewood, CA"),
    dict(external_ref="rose-bowl-aquatics-center", name="Rose Bowl Aquatics Center", zone="Pasadena",
         sport_use="Diving", geocode_query="Rose Bowl Aquatics Center, Pasadena, CA"),
    dict(external_ref="valley-complexes-sepulveda-basin", name="Valley Complexes 1-4 (Sepulveda Basin)",
         zone="Valley", sport_use="3x3 Basketball, BMX Freestyle, BMX Racing, Modern Pentathlon, Skateboarding",
         geocode_query="Sepulveda Basin Recreation Area, Los Angeles, CA", fuzzy=True),
    dict(external_ref="comcast-squash-center", name="Comcast Squash Center at Universal Studios",
         zone="Universal City", sport_use="Squash",
         geocode_query="Universal Studios Hollywood, Universal City, CA"),
    dict(external_ref="venice-beach-boardwalk", name="Venice Beach Boardwalk", zone="Venice",
         sport_use="Marathon (start), Road Cycling (race start)",
         geocode_query="Venice Beach Boardwalk, Venice, Los Angeles, CA", fuzzy=True),
    dict(external_ref="venice-beach", name="Venice Beach", zone="Venice", sport_use="Triathlon",
         geocode_query="Venice Beach, Los Angeles, CA",
         lat=33.97657143605985, lng=-118.46676819870399),  # user-corrected — Google's APPROXIMATE was off
    dict(external_ref="riviera-country-club", listed=False, name="Riviera Country Club", zone="Riviera",
         sport_use="Golf",
         geocode_query="Riviera Country Club, Pacific Palisades, Los Angeles, CA"),
    dict(external_ref="alamitos-beach-stadium", listed=False, name="Alamitos Beach Stadium", zone="Long Beach",
         sport_use="Beach Volleyball", geocode_query="Alamitos Beach, Long Beach, CA",
         lat=33.76404993538532, lng=-118.17663578290241),  # user-corrected — Google's APPROXIMATE was off
    dict(external_ref="long-beach-aquatics-center", listed=False, name="Long Beach Aquatics Center", zone="Long Beach",
         sport_use="Artistic Swimming, Water Polo",
         geocode_query="Long Beach Aquatics Center, Long Beach, CA", fuzzy=True),
    dict(external_ref="long-beach-arena", listed=False, name="Long Beach Arena", zone="Long Beach",
         sport_use="Handball",
         geocode_query="Long Beach Arena, Long Beach, CA"),
    dict(external_ref="long-beach-climbing-theater", listed=False, name="Long Beach Climbing Theater",
         zone="Long Beach", sport_use="Sport Climbing",
         geocode_query="Long Beach Convention Center, Long Beach, CA", fuzzy=True),
    dict(external_ref="long-beach-target-shooting-hall", listed=False, name="Long Beach Target Shooting Hall",
         zone="Long Beach", sport_use="Shooting (Rifle & Pistol)",
         geocode_query="Long Beach Convention Center, Long Beach, CA", fuzzy=True),
    dict(external_ref="marine-stadium", listed=False, name="Marine Stadium", zone="Long Beach",
         sport_use="Canoe Sprint, Rowing", geocode_query="Marine Stadium, Long Beach, CA"),
    dict(external_ref="belmont-shore", listed=False, name="Belmont Shore", zone="Long Beach",
         sport_use="Open Water Swimming, Coastal Rowing, Sailing (Windsurf & Kite)",
         geocode_query="Belmont Shore, Long Beach, CA",
         lat=33.754561087793135, lng=-118.13730405375101),  # user-corrected — Google's APPROXIMATE was off
    dict(external_ref="port-of-los-angeles", listed=False, name="Port of Los Angeles", zone="Port of LA",
         sport_use="Sailing (Dinghy, Skiff, Multihull)",
         geocode_query="Port of Los Angeles, San Pedro, Los Angeles, CA",
         lat=33.71501589956295, lng=-118.27517059180938),  # user-corrected — Google's APPROXIMATE was off
    dict(external_ref="carson-stadium", listed=False, name="Carson Stadium (Dignity Health Sports Park)", zone="Carson",
         sport_use="Archery, Rugby Sevens", geocode_query="Dignity Health Sports Park, Carson, CA"),
    dict(external_ref="carson-velodrome", listed=False, name="Carson Velodrome", zone="Carson",
         sport_use="Track Cycling",
         geocode_query="VELO Sports Center, Carson, CA"),
    dict(external_ref="carson-courts", listed=False, name="Carson Courts", zone="Carson", sport_use="Tennis",
         geocode_query="Dignity Health Sports Park Tennis Center, Carson, CA", fuzzy=True),
    dict(external_ref="carson-field", listed=False, name="Carson Field", zone="Carson", sport_use="Hockey",
         geocode_query="Dignity Health Sports Park, Carson, CA", fuzzy=True),
    dict(external_ref="santa-anita-park", name="Santa Anita Park", zone="Arcadia", sport_use="Equestrian",
         geocode_query="Santa Anita Park, Arcadia, CA"),
    dict(external_ref="whittier-narrows-shooting", listed=False, name="Whittier Narrows Clay Shooting Center",
         zone="Whittier Narrows", sport_use="Shooting (Shotgun)",
         geocode_query="Whittier Narrows Recreation Area, South El Monte, CA", fuzzy=True),
    dict(external_ref="industry-hills-mtb", listed=False, name="Industry Hills MTB Course", zone="City of Industry",
         sport_use="Mountain Bike", geocode_query="Industry Hills Expo Center, City of Industry, CA", fuzzy=True),
    dict(external_ref="honda-center", listed=False, name="Honda Center", zone="Anaheim", sport_use="Indoor Volleyball",
         geocode_query="Honda Center, Anaheim, CA"),
    dict(external_ref="fairgrounds-cricket-stadium", listed=False, name="Fairgrounds Cricket Stadium (Fairplex)",
         zone="Pomona", sport_use="Cricket", geocode_query="Fairplex, Pomona, CA", fuzzy=True),
    dict(external_ref="trestles-state-beach", listed=False, name="Trestles State Beach", zone="Trestles Beach",
         sport_use="Surfing", geocode_query="Trestles Beach, San Clemente, CA",
         lat=33.38694373302476, lng=-117.59552450583985),  # user-corrected — Google's GEOMETRIC_CENTER was off
]

# Two venue names, geocoded independently, can legitimately land this close
# without being duplicates (e.g. the four Carson venues share one complex).
# Below this radius, treat a match as "probably the same physical venue."
DEDUPE_RADIUS_M = 150

DATA_SOURCE_NOTE = "LA28 Games Map venue list (subject to change) — see Claude Code Prompt, v1.7 registry phase"


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


@dataclass
class RegistrationOutcome:
    external_ref: str
    name: str
    status: str  # "registered" | "skipped_existing" | "skipped_duplicate" | "error"
    venue_id: int | None = None
    lat: float | None = None
    lng: float | None = None
    location_type: str | None = None
    confidence: str | None = None
    needs_review: bool = False
    detail: str | None = None


def _find_by_ref_or_name(db: Session, external_ref: str, name: str) -> Venue | None:
    row = db.execute(select(Venue).where(Venue.external_ref == external_ref)).scalars().first()
    if row:
        return row
    target = _normalize_name(name)
    for v in db.execute(select(Venue)).scalars().all():
        if _normalize_name(v.name) == target:
            return v
    return None


def _find_by_proximity(db: Session, lat: float, lng: float) -> Venue | None:
    """
    Only ever matches against a HAND-COLLECTED venue (external_ref IS
    NULL) — the existing 6, or any future hand-collected addition. This is
    a safety net against re-adding one of those under a slightly different
    name/geocode, nothing else.

    Deliberately does NOT match against other pipeline-registered venues,
    same-run or from an earlier run: several venues in this list genuinely
    share one parent complex's geocode (all four Carson venues, a few Long
    Beach temporary structures all resolving to the same Convention Center
    query) and would otherwise collapse into a single row purely because
    Google can't resolve anything finer — found live, against the real
    API, the first time this ran. Each carries its own external_ref, which
    is what actually keeps re-running this script idempotent per-venue.
    """
    candidates = db.execute(
        select(Venue).where(
            Venue.lat.is_not(None), Venue.lng.is_not(None), Venue.external_ref.is_(None),
        )
    ).scalars().all()
    for v in candidates:
        if haversine_m(lat, lng, float(v.lat), float(v.lng)) <= DEDUPE_RADIUS_M:
            return v
    return None


def register_venue(db: Session, spec: dict) -> RegistrationOutcome:
    """
    A spec carrying its own "lat"/"lng" (see the "user-corrected" entries
    in VENUES) skips geocoding entirely — a human already checked it
    against a map, so it's registered with confidence="high",
    source="user_verified", and is never flagged for review again. This is
    how a bad Google geocode gets fixed for good: in the source list, not
    just patched once in the database.
    """
    external_ref, name = spec["external_ref"], spec["name"]

    existing = _find_by_ref_or_name(db, external_ref, name)
    if existing:
        return RegistrationOutcome(external_ref, name, "skipped_existing", venue_id=existing.id)

    address = None
    if "lat" in spec and "lng" in spec:
        lat, lng, location_type, confidence, source = spec["lat"], spec["lng"], None, "high", "user_verified"
    else:
        try:
            geo = geocode_address(spec["geocode_query"])
        except GeocodeError as exc:
            return RegistrationOutcome(external_ref, name, "error", detail=str(exc))
        lat, lng, location_type, confidence, source = geo.lat, geo.lng, geo.location_type, geo.confidence, "geocoded"
        address = geo.formatted_address

    dup = _find_by_proximity(db, lat, lng)
    if dup:
        return RegistrationOutcome(
            external_ref, name, "skipped_duplicate", venue_id=dup.id,
            lat=lat, lng=lng, detail=f"within {DEDUPE_RADIUS_M}m of venue {dup.id} ({dup.name})",
        )

    venue = Venue(
        name=name,
        zone=spec["zone"],
        sport_use=spec["sport_use"],
        lat=lat,
        lng=lng,
        address=address,
        external_ref=external_ref,
        source=source,
        confidence=confidence,
        data_sources_summary=DATA_SOURCE_NOTE,
        listed=spec.get("listed", True),
    )
    db.add(venue)
    db.flush()

    needs_review = source != "user_verified" and (spec.get("fuzzy", False) or location_type != "ROOFTOP")
    return RegistrationOutcome(
        external_ref, name, "registered", venue_id=venue.id,
        lat=lat, lng=lng, location_type=location_type, confidence=confidence, needs_review=needs_review,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Register new LA28 venues (geocode + minimal row).")
    parser.add_argument("refs", nargs="*", help="external_ref slug(s) to register")
    parser.add_argument("--all", action="store_true", help="Register every venue in the LA28 list")
    args = parser.parse_args()
    if not args.all and not args.refs:
        parser.error("pass one or more external_ref slugs, or --all")

    specs = VENUES if args.all else [v for v in VENUES if v["external_ref"] in args.refs]
    found_refs = {v["external_ref"] for v in specs}
    for missing in set(args.refs) - found_refs:
        print(f"  UNKNOWN external_ref: {missing}", file=sys.stderr)

    outcomes: list[RegistrationOutcome] = []
    with Session(engine) as db:
        for spec in specs:
            outcome = register_venue(db, spec)
            outcomes.append(outcome)
        db.commit()

    print(f"\n{'venue':<45} {'status':<18} {'id':>4}  {'lat,lng':<22} {'precision':<20} {'conf':<8} review")
    print("-" * 130)
    for o in outcomes:
        coord = f"{o.lat:.5f},{o.lng:.5f}" if o.lat is not None else "-"
        print(
            f"{o.name:<45} {o.status:<18} {str(o.venue_id or '-'):>4}  {coord:<22} "
            f"{(o.location_type or '-'):<20} {(o.confidence or '-'):<8} "
            f"{'REVIEW' if o.needs_review else ''}"
            + (f"  ({o.detail})" if o.detail else "")
        )

    registered = [o for o in outcomes if o.status == "registered"]
    review = [o for o in registered if o.needs_review]
    errors = [o for o in outcomes if o.status == "error"]

    print(f"\n{len(registered)} registered, {len(review)} flagged for coordinate review, {len(errors)} error(s).")
    if review:
        print("\nCoordinates needing review before enrichment:")
        for o in review:
            print(f"  - {o.name} (id={o.venue_id}): {o.location_type}, confidence={o.confidence}")
    if errors:
        print("\nErrors:")
        for o in errors:
            print(f"  - {o.name}: {o.detail}")

    if registered:
        ids = " ".join(str(o.venue_id) for o in registered)
        print(f"\nTo enrich the newly-registered venues once confirmed:\n  python -m app.enrich_venue {ids}")


if __name__ == "__main__":
    main()
