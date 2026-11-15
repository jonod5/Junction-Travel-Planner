# UX Recommendations — November 2026

**Suggestions only. Nothing here is implemented.** Each one comes from something seen in the code or in the running app on the `demo` branch during the audit.

**Who this is for:** an international visitor to the Games. Probably on a phone, possibly with limited English and a limited data plan, new to Los Angeles, trying to reach a venue that has no parking.

Each item gives: **what**, **why it helps this user**, **where** in the code, **impact** (H/M/L), **effort** (S under a day, M a few days, L a week or more), and any **dependency or risk**.

Items that need data which does not exist yet are collected in [section 4](#4-blocked-on-data-we-do-not-have-yet), so they are not mistaken for something buildable now.

---

## 1. New features

### F-1 · Plan for a date and time, not only "right now"
- **What:** A "Leave at / Arrive by" control in the planner, sent as `departure_time` to the route engine.
- **Why:** The planner never sends a departure time, so every route is computed for the moment of the request. A visitor planning tonight for a 10:00 event tomorrow sees late-evening transit. The backend already accepts `departure_time` and caches by 5-minute bucket; only the UI is missing.
- **Where:** `frontend/lib/store.tsx` (`optimizeLeg` omits it), `frontend/app/(tabs)/planner.web.tsx` (wizard and leg header), `app/routers/routes.py` (already supports it). "Arrive by" needs an `arrival_time` pass-through in `app/services/directions.py`.
- **Impact:** H · **Effort:** S for "leave at", M with "arrive by"
- **Dependency / risk:** Google returns scheduled transit only as far ahead as agencies publish (weeks, not years), so 2028 dates will not work until then. Label results "based on today's schedules".

### F-2 · Start from where the visitor actually is: a hotel, an address, or current location
- **What:** Free-text place search and a "use my location" button for the trip origin.
- **Why:** Today a stop can only be one of 15 venues or 5 airports (`StopSearch` merges `useVenues()` with `AIRPORTS` and nothing else). Almost no visitor starts at a venue. This is the largest gap between the app and a real trip.
- **Where:** `frontend/components/StopSearch.tsx`, `frontend/lib/api.ts` (no `searchPlaces` call yet), `app/routers/places.py` (exists; now cached and rate-limited, but it returns name and address only, so it needs to return coordinates too).
- **Impact:** H · **Effort:** M
- **Dependency / risk:** Places Text Search is billed per call. The cache and the 10/min limit added in this audit cap that. Coordinates in query strings end up in access logs (audit SEC-20). Browser geolocation needs a permission prompt and HTTPS.

### F-3 · Saved itineraries that open without a connection
- **What:** Show a saved itinerary straight from its stored snapshot, with a "refresh live times" button, instead of recomputing every leg first. Add a service worker that caches the app shell and the venue list.
- **Why:** Reopening a saved trip creates a new trip, re-adds each stop and re-runs the engine for every leg (`hydrateFromSnapshot`), so it needs a good connection at exactly the moment a visitor is underground or roaming. The snapshot already contains the chosen option with its steps and polylines. There is a PWA manifest but no service worker, so "Add to Home Screen" gives an icon that shows a blank page offline.
- **Where:** `frontend/lib/store.tsx` (`hydrateFromSnapshot`), `frontend/app/itineraries.tsx`, `frontend/public/` (service worker), `frontend/app/+html.tsx` (registration).
- **Impact:** H · **Effort:** M
- **Dependency / risk:** Map tiles cannot be cached under the Google Maps terms, so offline shows the step list, not the map. A snapshot view must show its saved date clearly.

### F-4 · Step-free routing for Paralympic and mobility-limited spectators
- **What:** A "step-free / wheelchair accessible" preference that requests accessible transit routes and avoids bike and scooter legs.
- **Why:** The app targets the Paralympic Games too, and nothing in it addresses accessibility: no preference, no accessible-route request, no elevator information. The only related data is a taxi "accessible zone" text field on some venues.
- **Where:** `frontend/components/ModePreferencesChecklist.tsx`, `app/routers/routes.py` (a new request field), `app/services/directions.py` (request parameters), `app/services/route_engine.py` (filter candidates before scoring; do not touch the weights).
- **Impact:** H · **Effort:** M
- **Dependency / risk:** First check what the Directions API offers for wheelchair-accessible transit; it has a `less_walking` preference, and anything beyond that may need Google's newer Routes API. Filtering which candidates are offered is allowed; changing scores is not (invariant 2). Live elevator status is in section 4.

### F-5 · A day plan across several venues
- **What:** Let each stop carry an event start time, and show for each leg "leave by 08:40 to arrive 60 minutes before".
- **Why:** The planner already chains stops into legs, but a visitor with two sessions in one day has to work out the timing by hand. The venue data already holds recommended arrival windows (`congestion_tdm.recommended_arrival_hrs_before_*`).
- **Where:** `frontend/lib/store.tsx` (`SavedPlanSnapshot` gains per-stop times), `planner.web.tsx` leg cards, `app/routers/venues.py` (already returns the arrival window).
- **Impact:** M · **Effort:** M
- **Dependency / risk:** Builds on F-1. Arrival windows are normal-day figures for most venues and must be labelled as such.

### F-6 · Show the fare a visitor will actually pay
- **What:** A short "how to pay" block on transit options: TAP card or contactless, where to get one, and the day cap.
- **Why:** The engine models `$1.75` per boarding with a `$5` daily cap, but a visitor sees only "~$3.50". They do not know that LA Metro needs a TAP card or what that is. The only help is a "Metro TAP fares" link out to an English page.
- **Where:** `app/services/fares.py` (constants and sources already there), `frontend/app/(tabs)/planner.web.tsx` step list, `frontend/lib/deeplinks.ts`.
- **Impact:** M · **Effort:** S
- **Dependency / risk:** Fares are flagged "verify" in `docs/estimates-to-verify.md`. Do not add new numbers; show the existing ones with their date.

### F-7 · Notify when a saved trip's service changes
- **What:** For an upcoming saved itinerary, re-check it the day before and on the day, and show a notice if a line it uses is not running.
- **Why:** The backend already tracks whether a line has vehicles running (`live_status_for_line`), but the only screen that shows it is the mode-comparison screen (`comparison.tsx`), which the web planner does not use.
- **Where:** `app/ingest/transit_rt.py`, `app/routers/vehicles.py`, `frontend/app/itineraries.tsx`.
- **Impact:** M · **Effort:** L (needs a scheduled job and web push, or a check on open as a cheaper first step)
- **Dependency / risk:** When a Swiftly agency feed errors (a code comment mentions the rail agency returning 403), status falls back to "scheduled", so the notice would be silent. Real service alerts are in section 4.

### F-8 · After-the-event guidance
- **What:** A "leaving the venue" view: which exits lead to which station, known congested exit roads, and where the rideshare pickup zone is.
- **Why:** Getting out is harder than getting in, and the data is already collected for the six original venues (`known_congestion_exit_roads`, `rideshare_zone_description`, `curbside_restrictions`). It sits three taps deep in the venue panel.
- **Where:** `frontend/components/VenueDetailPanel.tsx`, `app/routers/venues.py`.
- **Impact:** M · **Effort:** S for the six venues with data
- **Dependency / risk:** The nine registered venues have no curb or congestion data yet. Show nothing for them; do not infer it (invariant 3).

### F-9 · Decide what to do about e-bikes
- **What:** Either model e-bikes as their own option with their own fare, or leave them out of route options on purpose and stop showing them as a separate marker type.
- **Why:** The map shows live e-bikes (Bird has them in Venice), but the engine cannot use them. Until this audit, having one near a trip endpoint could crash the request (BUG-01). They are now ignored by the engine.
- **Where:** `app/services/route_engine.py` (`MODE_LABEL`, `_swappable`), `app/services/fares.py`, `frontend/lib/store.tsx` (`ROUTE_MODES`).
- **Impact:** L · **Effort:** S
- **Dependency / risk:** A new mode changes the candidate set, so the ranking snapshot must be regenerated on purpose. Needs a sourced e-bike price.

---

## 2. Cosmetic adjustments

### C-1 · The no-parking banner fails colour contrast
- **What:** Darken the banner green or use dark text.
- **Why:** The single most important message in the app is white text on `#48BB78`. That is a contrast ratio of about 2.4:1; WCAG AA needs 4.5:1. It is hard to read in sunlight, which is where it will be read.
- **Where:** `frontend/components/PolicyBanner.tsx:45`, `frontend/constants/theme.ts:11` (`sagebrush`).
- **Impact:** H · **Effort:** S

### C-2 · Secondary text is too light
- **What:** Darken `mutedFg`.
- **Why:** `#8896B8` on white is about 3.0:1. It is used for placeholders, distances and helper text across the planner.
- **Where:** `frontend/constants/theme.ts:30`.
- **Impact:** M · **Effort:** S

### C-3 · The "BEST" badge is 9 px gold on white
- **What:** Make the top-ranked option obvious: a filled badge, readable size, and a word that says why ("Fastest for the price").
- **Why:** It is the app's recommendation, and it is the smallest text on the screen at roughly 2:1 contrast (`#F59E0B` on white).
- **Where:** `frontend/app/(tabs)/planner.web.tsx:1124,1356` (`bestBadge`).
- **Impact:** M · **Effort:** S

### C-4 · A four-hour walk is listed like any other option
- **What:** Collapse impractical options ("Walk · 4h 28m") under a "More options" row, or grey them out.
- **Why:** The engine keeps walking on purpose so nothing is hidden, but in the list it has the same weight as transit. Venice Beach to the Coliseum shows three cards and one of them is a 4.5-hour walk.
- **Where:** `frontend/app/(tabs)/planner.web.tsx:1113-1131`. Presentation only; the engine output is unchanged.
- **Impact:** M · **Effort:** S

### C-5 · Dark-mode devices get a black page edge
- **What:** Either support dark mode or remove the dark body background.
- **Why:** `+html.tsx` sets the page background to `#000` when the device prefers dark, but every screen uses the light theme. On a dark-mode phone the area around the app and the overscroll are black.
- **Where:** `frontend/app/+html.tsx:41-48`, `frontend/constants/theme.ts`.
- **Impact:** L · **Effort:** S to remove, L to support dark mode properly

### C-6 · One type of loading state
- **What:** Skeleton cards for route options and the venue panel instead of a spinner.
- **Why:** There are 24 `ActivityIndicator`s. A leg takes several seconds to compute (four to six Directions calls), and a spinner gives no sense of what is coming or how long.
- **Where:** `planner.web.tsx` leg cards, `VenueDetailPanel.tsx`.
- **Impact:** M · **Effort:** S

### C-7 · Map marker clutter at city zoom
- **What:** Cluster or hide the transit, bike and rideshare markers until the map is zoomed in; keep venue pins always visible.
- **Why:** At the default zoom the map shows 15 venue pins, 5 airports and about 23 hand-collected transit points, all around downtown, overlapping. The legend covers a third of the map on a phone.
- **Where:** `planner.web.tsx:683-800`, `frontend/constants/venue-transit.ts`.
- **Impact:** M · **Effort:** M

### C-8 · Route line legibility
- **What:** A white casing under every mode's polyline (transit already has one) and a fixed colour key in the step list that matches the map.
- **Why:** Walking is a dashed blue line on a map whose roads and water are also blue-grey.
- **Where:** `planner.web.tsx:618-660`, `MODE_COLORS` at `:109`.
- **Impact:** L · **Effort:** S

### C-9 · Styling in one place
- **What:** Move the 98 hard-coded hex colours and the inline HTML popup styles to theme tokens.
- **Why:** C-1 to C-3 are each a one-line change only if colours live in one file. This is audit finding MESS-08.
- **Where:** `frontend/constants/theme.ts`, all screens.
- **Impact:** L (for users) · **Effort:** M

### C-10 · Respect reduced motion on the landing page everywhere
- **What:** The landing page has a `useReducedMotion` helper; apply the same check to the map's animated pans and zooms.
- **Where:** `frontend/components/landing/motion.tsx:28`, `frontend/app/(tabs)/planner.web.tsx` (map `panTo`/`fitBounds` calls).
- **Impact:** L · **Effort:** S

---

## 3. Overall UX updates

### U-1 · The landing page and the survey are English-only
- **What:** Move their strings into the locale files.
- **Why:** The first screen a Spanish, French or Chinese speaker sees ("NO CAR NEEDED.", "READY TO PLAN?") is not translated, and neither is any of the survey ("Which of these trips would you choose?"). For the survey that also biases who can respond. Audit finding MESS-05 lists every file.
- **Where:** `frontend/app/index.tsx`, `frontend/components/landing/LearnMoreSections.tsx`, `frontend/app/survey.tsx`, `frontend/app/_layout.tsx:130`.
- **Impact:** H · **Effort:** M (about 80 strings × 3 languages, plus native review)
- **Dependency / risk:** Survey wording is part of the instrument; translations need IRB sign-off.

### U-2 · Route option names come from the backend in English
- **What:** Build the option label in the frontend from `option.modes` using the existing `modes.shortLabel.*` keys.
- **Why:** Cards show `opt.label` as sent by the engine ("Scooter → Transit", "Rideshare"), in English, in every language. The translated mode names already exist.
- **Where:** `frontend/app/(tabs)/planner.web.tsx:1123`, `app/services/route_engine.py` (`MODE_LABEL` stays as is).
- **Impact:** M · **Effort:** S

### U-3 · Error messages are raw English strings from the API
- **What:** Map error codes to translated messages, and say what to do next ("Try again in a minute").
- **Why:** The client shows whatever `detail` the backend returned. A visitor hitting the rate limit sees "Rate limit exceeded — max 15 requests per 60s".
- **Where:** `frontend/lib/api.ts` (`errorMessage`), `frontend/lib/store.tsx`, locale files.
- **Impact:** M · **Effort:** S

### U-4 · Tell screen readers and the browser which language is on screen
- **What:** Set `document.documentElement.lang` when the language changes, and pass `language` and `region` to the Maps script.
- **Why:** `<html lang="en">` is fixed, so a screen reader reads Spanish or Chinese text with English pronunciation. The Maps SDK is loaded without a language, so map labels follow the browser, not the app.
- **Where:** `frontend/app/+html.tsx:10`, `frontend/lib/i18n.ts` (`changeLanguage`), `planner.web.tsx:87`.
- **Impact:** M · **Effort:** S

### U-5 · Explain why an option is ranked first
- **What:** One plain line under the top option: "12 min faster than the next option for $1.75 more", built from the numbers already on screen.
- **Why:** The API returns a full `score_breakdown` for every option and the UI shows none of it. For a research app about mode choice, the trade-off is the point.
- **Where:** `frontend/app/(tabs)/planner.web.tsx` option cards; `RouteOption.score_breakdown` in `frontend/lib/api.ts`.
- **Impact:** M · **Effort:** S
- **Dependency / risk:** Explain with times and costs only. Do not re-rank or re-score in the frontend (invariant 2).

### U-6 · Make the car-free message part of the route, not only a banner
- **What:** When rideshare is selected, show where it can actually drop off (the venue's rideshare zone and the walk from there), and say plainly that there is no parking.
- **Why:** The banner is general. The moment the message matters is when someone picks a car. The drop-off data exists for six venues.
- **Where:** `planner.web.tsx` rideshare option, `VenueDetailPanel.tsx`, `curb_dropoffs` from `GET /api/venues/{id}`.
- **Impact:** H · **Effort:** S for venues with data
- **Dependency / risk:** Games-time drop-off zones are not published (section 4). Label current data "typical event day".

### U-7 · Show what is still unknown
- **What:** Render the "awaiting official Games-time information" state in the venue panel.
- **Why:** The backend returns a `games_time_official` block for every venue (the Tier-3 scaffold), designed to say that official data is pending. The frontend type does not include it, so it is never shown. The Tier-1 rideshare estimate (`rideshare_estimate_usd`) is dropped the same way.
- **Where:** `frontend/lib/api.ts` (`VenueDetail`, `TransitAccess` types), `frontend/components/VenueDetailPanel.tsx`.
- **Impact:** M · **Effort:** S

### U-8 · Planner flow friction
- **What:** (a) Start with one question, "Where are you going?", and add the origin after. (b) Remember mode preferences in the browser for signed-out users.
- **Why:** The wizard asks for every stop, then preferences, then shows the trip. Preferences are kept only in memory, so every visit starts from all modes on unless the user is signed in.
- **Where:** `planner.web.tsx:373-378` (wizard state), `frontend/lib/store.tsx:78` (`preferences` is session-only).
- **Impact:** M · **Effort:** M

### U-9 · Phone ergonomics
- **What:** (a) Minimum 44 px touch targets on the map legend chips, the "+" on venue rows and the pin/rename/delete icons. (b) A native date picker instead of typing `YYYY-MM-DD`.
- **Why:** Icon buttons in the itinerary list are small glyphs with 8 px of `hitSlop`. On native the trip date is a free-text field with a format hint.
- **Where:** `frontend/app/itineraries.tsx:252-261`, `frontend/components/SaveItineraryDialog.tsx:80-87`.
- **Impact:** M · **Effort:** S

### U-10 · Screen-reader coverage (WCAG 2.2 AA)
- **What:** Label every control, announce loading and results, and give route options a proper radio group.
- **Why:** 83 `Pressable`s, 57 accessibility labels. Route option cards are `role="button"` with no selected state and no label, so the chosen route is not announced. Fifteen labels are hard-coded English. The map has no text alternative; the step list is the alternative and should be reachable without the map.
- **Where:** `planner.web.tsx:1116-1120`, `components/OptionCard.tsx` (already does this correctly and can be reused), `VenuePicker*.tsx`.
- **Impact:** H · **Effort:** M
- **Dependency / risk:** Needs testing with VoiceOver and TalkBack; no automated accessibility check exists.

### U-11 · Page weight on a limited data plan
- **What:** (a) Stop shipping the native-only screens in the web bundle. (b) Split the bundle so the landing page does not download the planner. (c) Load the Maps SDK with `loading=async`. (d) Check that Vercel serves the bundle compressed and cached.
- **Why:** The web build is one 3.4 MB JavaScript file loaded on the landing page, before the visitor has chosen to plan anything. It includes `planner.tsx`, `map.tsx`, `routes.tsx` and `comparison.tsx`, which the web app does not use.
- **Where:** `frontend/app/(tabs)/` (see audit MESS-07), `planner.web.tsx:82-92`, `frontend/vercel.json`.
- **Impact:** M · **Effort:** M
- **Dependency / risk:** Depends on deciding what happens to the native flow.

### U-12 · Route requests are slow and count against a small limit
- **What:** Fetch the per-mode Directions calls for a leg in parallel, and show transit first while the other modes load.
- **Why:** One leg makes four to six sequential Google calls. Opening a saved four-stop itinerary runs three legs back to back, and each is one of the client's 15 optimize requests per minute.
- **Where:** `app/services/route_engine.py` (`optimize`, the builders run in sequence), `app/services/directions.py`.
- **Impact:** M · **Effort:** M
- **Dependency / risk:** Parallel fetching must not change which candidates exist or their order. The ranking snapshot test (`tests/test_route_engine_snapshot.py`) guards that.

### U-13 · Onboarding in one screen
- **What:** Replace the long landing page with three lines and one button for returning or mobile visitors: what it is, that the Games have no parking, "Plan a trip".
- **Why:** The landing page is a marketing scroll. On a phone the planner is one tap and a 3.4 MB load away.
- **Where:** `frontend/app/index.tsx`.
- **Impact:** L · **Effort:** S

### U-14 · Privacy and consent, said plainly
- **What:** Real privacy and terms pages, and a one-line note at sign-in and at the survey about what is stored.
- **Why:** The Settings links go to `example.com` (audit SEC-18). The app stores Google identities and survey choices.
- **Where:** `frontend/app/settings.tsx:271,276`, `frontend/app/survey.tsx`.
- **Impact:** M · **Effort:** S once the text exists
- **Dependency / risk:** Wording needs IRB and university review.

---

## 4. Blocked on data we do not have yet

None of these can be built honestly today. Each needs a data source that does not exist or is not published. They are listed so the UI can be designed to receive them.

| # | Feature | What it is waiting for |
|---|---|---|
| D-1 | Games-time car-restricted zones, official drop-off points, spectator shuttles and arrival windows per venue | Official LA28 venue transport plans. The Tier-3 table and API field are ready and empty (see U-7). |
| D-2 | Park-and-ride options | Real lot locations and the car-free zone boundaries. The engine deliberately omits park-and-ride until then. |
| D-3 | Games-time transit service: extra frequency, special lines, station closures | LA Metro's Games service plan and updated GTFS feeds. |
| D-4 | Un-hiding the 18 venues outside the Metro core | GTFS feeds for Long Beach Transit, OCTA and Foothill Transit ingested (see `docs/known-gaps.md`), then `listed = true`. |
| D-5 | Live elevator and escalator status for step-free routes (extends F-4) | A machine-readable outage feed from LA Metro. |
| D-6 | Service alerts and delay predictions (extends F-7) | GTFS-RT alerts and trip-update feeds. Only vehicle positions are available today. |
| D-7 | Crowding and post-event egress predictions | Venue schedules, attendance and historical station loads. |
| D-8 | Curb, parking and congestion detail for the 9 registered venues | Tier-2 extraction reviewed by a person, or official data. Must not be inferred from the six hand-collected venues. |
| D-9 | Free or discounted Games transit fares | An official fare policy for the Games. Current fares are normal-day figures and are labelled as estimates. |
| D-10 | Live rideshare prices | Uber and Lyft price APIs are enterprise-gated. The modelled estimate stays. |

---

## Top 10, highest impact for the least effort first

| # | Item | Impact | Effort | Good candidate for a Claude Code prompt? |
|---|---|---|---|---|
| 1 | **C-1** Fix the no-parking banner's contrast (with C-2 and C-3) | H | S | Yes. Small, checkable with a contrast script. |
| 2 | **F-1** "Leave at" date and time in the planner | H | S | Yes. Backend support exists; scope is one control and one request field. |
| 3 | **U-6** Rideshare option shows the real drop-off zone and "no parking" | H | S | Yes, for the six venues with data. |
| 4 | **U-2 + U-3 + U-4** Localize option labels and errors; set the page language | M | S | Yes. Mechanical, with a clear done-test per language. |
| 5 | **U-7** Show the "awaiting official data" state and the Tier-1 rideshare estimate | M | S | Yes. Types plus one panel section. |
| 6 | **U-5** One-line explanation of the top-ranked option | M | S | Yes, with the invariant "do not re-rank in the frontend" stated in the prompt. |
| 7 | **F-2** Start from a hotel, an address or the current location | H | M | Yes, as its own prompt. Needs the Places response extended with coordinates. |
| 8 | **U-1** Translate the landing page and the survey | H | M | Partly. Extracting strings is a good prompt; the translations need native and IRB review. |
| 9 | **F-3** Saved itineraries open from their snapshot; add a service worker | H | M | Yes, in two prompts (snapshot view first, service worker second). |
| 10 | **U-10** Screen-reader pass on the planner | H | M | Partly. Labels and roles are a good prompt; verification needs a person with VoiceOver or TalkBack. |

Next after these: **F-4** step-free routing (H impact, M effort, and central to the Paralympic audience) and **U-12** parallel route fetching.
