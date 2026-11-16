# Proposed `.env.example` (audit MESS-02)

`.env.example` could not be edited during the audit: the workspace permission
settings block every `.env*` file, and that rule was left alone. This is the
proposed replacement. Copy the block below over `.env.example`.

What changes from the current template:

- **Removed** (nothing reads them): `GEMINI_API_KEY`, `SPIN_GBFS_BASE_URL`,
  `BIRD_GBFS_BASE_URL`, `LA_METRO_GBFS_BASE_URL`, `GTFS_RT_VEHICLES_URLS`,
  `GTFS_RT_API_KEY`.
- **Added** (the code reads them, the template never listed them): the
  admin keys, CORS, rate-limit and proxy settings, the docs toggle, the
  Tier-2 extraction key, the Swiftly agency list, the GBFS override, pool
  tuning, and the three frontend variables.

```dotenv
# ── PostgreSQL ──────────────────────────────────────────────────────────────
POSTGRES_USER=junction
POSTGRES_PASSWORD=changeme
POSTGRES_DB=junctiondb
# Full URL consumed by SQLAlchemy engine and Alembic env.py.
# Inside Docker the hostname is "db" (the compose service name).
# Outside Docker use "localhost" instead.
DATABASE_URL=postgresql+psycopg2://junction:changeme@db:5432/junctiondb

# ── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ── Google Maps Platform (server key) ───────────────────────────────────────
# Server-side only — never expose to the frontend or commit to git.
# In Google Cloud, restrict this key to the Directions, Places and Geocoding
# APIs. It must NOT be the same key as EXPO_PUBLIC_GOOGLE_MAPS_KEY below.
GOOGLE_MAPS_API_KEY=your_server_side_maps_key_here

# ── GTFS static feeds (python -m app.ingest.gtfs_static) ────────────────────
# Comma-separated list of GTFS .zip URLs — all feeds are merged in one ingest.
GTFS_STATIC_URLS=https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip,https://gitlab.com/LACMTA/gtfs_bus/-/raw/master/gtfs_bus.zip

# ── Live transit (Swiftly GTFS-RT) ───────────────────────────────────────────
# Optional. Without a key the live endpoints report "scheduled".
SWIFTLY_API_KEY=your_swiftly_api_key_here
# SWIFTLY_AGENCIES=lametro,lametro-rail

# ── Micromobility (GBFS) ─────────────────────────────────────────────────────
# Optional override of the built-in feed roots: bird=<url>,spin=<url>,metro-bike-share=<url>
# GBFS_PROVIDER_ROOTS=

# ── Supabase auth (backend) — never in the frontend or committed ────────────
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_JWT_SECRET=jwt_secret_here      # only for legacy HS256 projects
SUPABASE_SERVICE_KEY=service_key_here    # account deletion (Admin API)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Extra allowed browser origins, comma-separated (localhost dev ports are built in).
# CORS_ORIGINS=https://your-frontend.example.com

# ── Rate limiting ────────────────────────────────────────────────────────────
# Number of reverse proxies in front of the API. 0 for local dev. Behind a
# host's edge proxy set 1; with a second proxy in front of that (e.g. the
# Vercel /api rewrite) set 2. See app/rate_limit.py before changing it.
RATE_LIMIT_TRUSTED_PROXY_HOPS=0
# RATE_LIMIT_GLOBAL_PER_MIN=300
# RATE_LIMIT_DIRECTIONS_PER_MIN=20
# RATE_LIMIT_OPTIMIZE_PER_MIN=15
# RATE_LIMIT_PLACES_PER_MIN=10
# RATE_LIMIT_SURVEY_SESSION_PER_MIN=10

# ── API docs ─────────────────────────────────────────────────────────────────
# Set to false on a public deployment to turn off /docs, /redoc, /openapi.json.
# API_DOCS_ENABLED=true

# ── Admin endpoints (X-Admin-Key header). Unset = endpoint disabled. ─────────
# Use long random values, different from each other:  openssl rand -hex 32
# VENUE_ADMIN_KEY=
# SP_ADMIN_KEY=

# ── Tier-2 venue extraction CLI (python -m app.extract_venue) ───────────────
# ANTHROPIC_API_KEY=
# VENUE_EXTRACT_MODEL=claude-sonnet-5

# ── Connection pool / workers (optional tuning) ─────────────────────────────
# DB_POOL_SIZE=10
# DB_MAX_OVERFLOW=20
# DB_POOL_TIMEOUT=30
# WEB_CONCURRENCY=2

# ── Frontend (frontend/.env.local, and the Vercel project settings) ─────────
# These ship in the public bundle. The anon key is public by design.
EXPO_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=anon_key_here
# Browser key for the Maps JavaScript SDK: restrict it to your site's HTTP
# referrers and to the Maps JavaScript API only.
EXPO_PUBLIC_GOOGLE_MAPS_KEY=your_referrer_restricted_browser_key_here
# Only for native or local dev; leave unset on Vercel.
# EXPO_PUBLIC_API_URL=http://localhost:8000
```
