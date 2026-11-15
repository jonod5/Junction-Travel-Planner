# Known Gaps — follow-up work, not bugs

Things that work as designed but leave a real hole, tracked here so they
don't get rediscovered from scratch. Contrast with `docs/estimates-to-verify.md`,
which tracks pricing-model numbers that need re-checking against a source —
this file is for scope gaps: something the app doesn't do yet, and why.

---

## GTFS static coverage is LA Metro-only — 8 venues have no "nearest transit stop" data

**Found:** 2026-09-28, registering the 27 new LA28 venues (v1.7 registry phase).

`app/ingest/gtfs_static.py` only ingests LA Metro's own GTFS static feed.
`app/services/venue_enrichment.py`'s Tier-1 "nearest transit stop" enrichment
(`find_nearest_transit()`) queries that mirror, so it comes back empty for any
venue with no LA Metro stop within the 1200m search radius — not because
there's no transit there, but because our own feed doesn't know about it.

Affected venues (0 GTFS stops found within radius):

| Venue | id | Zone | Actual transit agency |
|---|---|---|---|
| Alamitos Beach Stadium | 17 | Long Beach | Long Beach Transit |
| Long Beach Aquatics Center | 18 | Long Beach | Long Beach Transit |
| Marine Stadium | 20 | Long Beach | Long Beach Transit |
| Belmont Shore | 21 | Long Beach | Long Beach Transit |
| Industry Hills MTB Course | 28 | City of Industry | Foothill Transit |
| Honda Center | 29 | Anaheim | OCTA |
| Fairgrounds Cricket Stadium (Fairplex) | 30 | Pomona | Foothill Transit |
| Trestles State Beach | 31 | Trestles Beach | OCTA / Metrolink |

**This does NOT mean these venues are car-only.** Verified live
(`fetch_directions(..., mode="transit")` via Google Directions) that real
transit routes exist and are returned for all 8 — Google's transit data
covers every CA agency, not just the one we've mirrored. `/api/routes`
(`app/services/route_engine.py`) calls Google Directions directly per
candidate mode and never touches our GTFS mirror, so actual trip-planning
to these venues already works correctly. What's missing is narrower: the
venue detail page's "nearest stop / walk time / bus lines" info card
(Tier-1's own enrichment output), not routing.

**Fix:** ingest Long Beach Transit's, OCTA's, and Foothill Transit's GTFS
static feeds alongside LA Metro's — a new `app/ingest/*_gtfs_static.py` per
agency (or a parameterized version of the existing one), then re-run
`python -m app.enrich_venue 17 18 20 21 28 29 30 31`. New scope, not a bug
fix — not started.

**Hidden from the app (v1.7b):** these 8 venues are now hidden from the app
(`venue.listed = false`, migration 0017), along with 10 other venues outside
LA Metro's service area (Carson, Riviera, Port of LA, Whittier Narrows) — the
intended scope is the LA Metro-served core. Nothing is deleted: they stay in
the database, `GET /api/venues/{id}` still serves them, and the enrichment
pipeline still processes them. **Ingesting the other agencies' GTFS feeds
(Long Beach Transit, OCTA, Foothill Transit) is the prerequisite for
un-hiding them** — then set `listed = true` for the venue.

**Status:** ☐ not started
