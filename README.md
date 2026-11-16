# Junction: LA Trip Planner

A transit-first, multi-modal trip-planning application for visitors to events in Los Angeles. The app helps a visitor who is unfamiliar with Los Angeles figure out how to reach each venue by public transit, walking, shared bikes and scooters, and ride-hailing, and compares those options by travel time, cost, and number of transfers.

Built as the engineering deliverable of a UCLA Samueli **Summer Undergraduate Research Program (SURP) 2026** project under Prof. Youngseo Kim (Civil & Environmental Engineering). The application also serves as the foundation for a second research purpose: a stated-preference (SP) travel-survey platform for studying traveler mode choice under car-free Games conditions.

> **Status:** research prototype. Some components (survey scenario data, non-English translations) are first-pass or awaiting external input — see notes below.

## Features

- **Multi-modal route optimization engine** — composes candidate itineraries per leg (transit backbone + walk / bike / scooter access, micromobility-only, ride-hailing, Metro Micro) and ranks them with a deterministic weighted score over travel time, fare cost, and transfers, adjusted to the traveler's mode preferences. Scoring is rule-based and reproducible (no LLM in the ranking path).
- **Live data integration** — LA Metro transit, real-time vehicle positions via Swiftly (GTFS-RT), and live shared bike/scooter availability via public GBFS feeds (Bird, Spin, Metro Bike Share). Metro Micro (on-demand microtransit) is included as a zone-limited option.
- **Hand-collected venue data** — source-verified parking, curb/drop-off, transit-access, and congestion information for the core venues, with a Games-time "no spectator parking" framing.
- **Unified planner UI** — a single full-bleed map screen: search venues/airports, build an itinerary, and compare ranked route options in one place. Responsive down to phone width (bottom-sheet layout) with an installable PWA manifest.
- **Deep links** — hand-off to Uber, Waymo, Bird, Spin, and Metro apps with trip context prefilled (no in-app booking).
- **Accounts & saved itineraries** — Google sign-in via Supabase Auth; save, rename, tag, pin, and revisit trips, organized into upcoming and past. Planning works fully anonymously; an account is only needed to save.
- **Multi-language** — English, Spanish, French, and Simplified Chinese UI, with localized turn-by-turn directions. (Non-English content is first-pass and flagged for native-speaker review.)
- **Stated-preference survey pipeline** — ingests choice-scenario data (CSV), presents respondents a sequence of choice tasks through the app's option-card UI, and records choices for discrete-choice analysis. (Skeleton; live data collection requires IRB approval.)

## Tech stack

**Backend** — FastAPI (Python), PostgreSQL, Redis (caching), SQLAlchemy + Alembic (migrations). All third-party API calls are proxied through the backend so vendor keys never reach the client (backend-proxy pattern); external responses are cached in Redis with appropriate TTLs.

**Frontend** — React Native + Expo (TypeScript), shared web + mobile codebase, Google Maps JS SDK on web. Auth via Supabase; internationalization via i18next.

**Infrastructure** — Docker + docker-compose for local development; backend + Postgres + Redis deployed on Railway, frontend web on Vercel (with an edge proxy to the backend), GitHub Actions for CI (lint + tests).

## Repository structure

```
app/            FastAPI backend — routers, models, services (route engine, fares), ingest (GTFS, GBFS, transit-RT)
alembic/        Database migrations
tests/          Backend test suite (pytest)
frontend/       Expo / React Native app (web + mobile)
docs/           Supporting docs (e.g., SP survey CSV format)
docker-compose.yml   Local backend + Postgres + Redis
Dockerfile           Backend container
railway.toml         Railway deployment config
```

## Getting started

### Prerequisites

- Docker + Docker Compose
- Node.js and npm (for the frontend)
- API keys / credentials for the services below (see Environment variables)

### 1. Configure environment

```bash
cp .env.example .env
# fill in the values (see the Environment variables section)
```

The frontend reads its own env from `frontend/.env.local` (Supabase URL + anon key, backend URL).

### 2. Run the backend (Postgres + Redis + API)

```bash
docker compose up --build          # starts db, redis, backend
docker compose exec backend alembic upgrade head   # apply migrations
docker compose exec backend python -m app.seed_venues   # seed venue data
```

The API is then available at `http://localhost:8000`.

### 3. Run the frontend

```bash
cd frontend
npm install
npm run web        # or: npm run ios / npm run android
```

## Environment variables

Set in `.env` (backend) unless noted. **Never commit real values** — `.env` is gitignored.

| Variable | Purpose |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Local Postgres credentials |
| `DATABASE_URL` | Postgres connection string |
| `REDIS_URL` | Redis connection string |
| `GOOGLE_MAPS_API_KEY` | Google Maps Platform (Directions, Places, Geocoding) — **server-side only**. Restrict it to those three APIs. |
| `GTFS_STATIC_URLS` | LA Metro GTFS static feed zips (comma-separated), for `python -m app.ingest.gtfs_static` |
| `SWIFTLY_API_KEY` / `SWIFTLY_AGENCIES` | Swiftly real-time transit (GTFS-RT vehicle positions) — **server-side only** |
| `GBFS_PROVIDER_ROOTS` | Optional override of the built-in Bird / Spin / Metro Bike Share GBFS roots (`bird=<url>,spin=<url>`) |
| `SUPABASE_URL` / `SUPABASE_JWT_SECRET` / `SUPABASE_SERVICE_KEY` | Supabase auth — verification + admin; **server-side only** |
| `CORS_ORIGINS` | Extra allowed browser origins (comma-separated), e.g. the deployed frontend |
| `RATE_LIMIT_TRUSTED_PROXY_HOPS` | Number of reverse proxies in front of the API, so rate limits key on the real client address (see `app/rate_limit.py`). `0` locally. |
| `RATE_LIMIT_GLOBAL_PER_MIN` / `RATE_LIMIT_DIRECTIONS_PER_MIN` / `RATE_LIMIT_OPTIMIZE_PER_MIN` / `RATE_LIMIT_PLACES_PER_MIN` / `RATE_LIMIT_SURVEY_SESSION_PER_MIN` | Optional rate-limit overrides |
| `API_DOCS_ENABLED` | Set to `false` on a public deployment to turn off `/docs`, `/redoc` and `/openapi.json` |
| `VENUE_ADMIN_KEY` | Shared secret for the venue review queue (`X-Admin-Key`). Unset = endpoint off. |
| `SP_ADMIN_KEY` | Shared secret for the survey CSV export (`X-Admin-Key`). Unset = endpoint off. |
| `ANTHROPIC_API_KEY` / `VENUE_EXTRACT_MODEL` | Tier-2 venue extraction CLI (`python -m app.extract_venue`) only |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `WEB_CONCURRENCY` | Optional connection-pool and worker tuning |

Frontend (`frontend/.env.local`, and the Vercel project settings):

| Variable | Purpose |
|---|---|
| `EXPO_PUBLIC_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_ANON_KEY` | Supabase values for the frontend (anon key is public by design) |
| `EXPO_PUBLIC_GOOGLE_MAPS_KEY` | Browser key for the Maps JavaScript SDK. It ships in the public bundle, so it must be a **separate key** from the server one, restricted to your site's HTTP referrers and to the Maps JavaScript API only. |
| `EXPO_PUBLIC_API_URL` | Backend URL for native or local dev. Leave unset on Vercel (the `/api` rewrite is used). |

## Research context

The application underpins a stated-preference survey platform for Transportation Demand Management (TDM) research: presenting travelers with realistic choice scenarios (varying travel time, cost, and walk time per mode) to study how they choose between modes near venues. Findings could inform questions such as the appropriate size of car-restricted zones, designated ride-hailing pickup/drop-off locations, shuttle service quality, and the impact of free/discounted transit and micromobility on access under car-free Games conditions. Real data collection is gated on IRB approval; this repository contains the instrument, not survey data.

## Acknowledgements

Developed by Jonathan Dau under the mentorship of Prof. Youngseo Kim, Department of Civil & Environmental Engineering, UCLA, through the UCLA Samueli Summer Undergraduate Research Program (SURP) 2026.
