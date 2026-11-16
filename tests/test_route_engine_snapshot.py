"""
Route-engine ranking regression snapshot (audit REF-01, invariant: route
ranking is deterministic and must not change under refactoring).

Each scenario feeds the engine a fixed origin, destination, preference set
and fixed (stubbed) Directions / GBFS inputs, and compares the FULL output —
candidate set, order, minutes, costs, transfers, scores, score breakdown,
weights — against tests/snapshots/route_engine_rankings.json, which was
recorded from the engine before any refactoring.

If this test fails, the engine's behaviour changed. That is never an
acceptable side effect of a refactor. If the change is intended (new
weights, a new candidate type), regenerate the snapshot on purpose:

    UPDATE_ROUTE_SNAPSHOT=1 pytest tests/test_route_engine_snapshot.py

and review the JSON diff like any other code change.
"""

import json
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest  # noqa: E402

from app.services import route_engine  # noqa: E402

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "route_engine_rankings.json"

# ── Fixed places ─────────────────────────────────────────────────────────────
DTLA = (34.0430, -118.2673)          # central LA — no Metro Micro zone, no airport
COLISEUM = (34.0141, -118.2879)
SOFI = (33.9535, -118.3392)          # inside the LAX/Inglewood Metro Micro zone
INTUIT = (33.9451, -118.3431)        # same zone
LAX = (33.9425, -118.4081)           # airport pickup fee applies
BUR = (34.2007, -118.3585)
ROSE_BOWL = (34.1613, -118.1676)


def _step(mode, distance_m, duration_s, instruction="", **extra):
    return {"mode": mode, "distance_m": distance_m, "duration_s": duration_s,
            "polyline": f"{mode[:1]}{distance_m}", "instruction": instruction, **extra}


def _transit(lead_s, ride_s, trail_s, boardings=1, lead_m=None, trail_m=None):
    steps = [_step("walking", lead_m if lead_m is not None else int(lead_s * 1.3), lead_s, "Walk to the station")]
    for i in range(boardings):
        steps.append(_step("transit", 6000 // boardings, ride_s // boardings, f"Ride line {i}",
                           transit_line=f"Line {i}", departure_stop=f"Stop {i}", arrival_stop=f"Stop {i + 1}"))
    steps.append(_step("walking", trail_m if trail_m is not None else int(trail_s * 1.3), trail_s, "Walk to the venue"))
    return {"mode": "transit", "distance_m": sum(s["distance_m"] for s in steps),
            "duration_s": sum(s["duration_s"] for s in steps), "polyline": "TRANSIT", "steps": steps}


def _simple(mode, distance_m, duration_s):
    return {"mode": mode, "distance_m": distance_m, "duration_s": duration_s, "polyline": mode.upper(),
            "steps": [_step(mode, distance_m, duration_s, f"{mode} the whole way")]}


LIVE_PRICING = [
    # A membership pass listed first (must be ignored), then a real per-minute plan.
    {"plan_id": "monthly", "name": "Monthly", "price": 17.0, "per_min_pricing": None},
    {"plan_id": "ride", "name": "Pay per ride", "price": 1.0,
     "per_min_pricing": [{"start": 0, "rate": 0.45, "interval": 1}]},
]

# name → (origin, destination, preferences, departure_time, directions-by-mode, micro types, pricing)
SCENARIOS = {
    "central_7km_all_modes": (
        DTLA, COLISEUM, None, None,
        {"transit": _transit(650, 900, 650), "walking": _simple("walking", 6000, 4300),
         "bicycling": _simple("bicycling", 7000, 1500), "driving": _simple("driving", 7000, 1000)},
        {"scooter", "bike"}, [],
    ),
    "short_hop_walk_bike_scooter": (
        DTLA, COLISEUM, None, None,
        {"transit": _transit(120, 300, 150), "walking": _simple("walking", 1400, 1050),
         "bicycling": _simple("bicycling", 1600, 400), "driving": _simple("driving", 1800, 420)},
        {"scooter"}, [],
    ),
    "two_transfers_long_walks_no_micro_nearby": (
        DTLA, ROSE_BOWL, None, 1_785_000_000,
        {"transit": _transit(700, 2700, 900, boardings=3), "walking": _simple("walking", 19000, 14000),
         "bicycling": _simple("bicycling", 21000, 4800), "driving": _simple("driving", 20000, 1700)},
        set(), [],
    ),
    "metro_micro_zone": (
        SOFI, INTUIT, None, None,
        {"transit": _transit(300, 420, 200), "walking": _simple("walking", 1500, 1150),
         "bicycling": _simple("bicycling", 1700, 430), "driving": _simple("driving", 1900, 380)},
        {"bike"}, [],
    ),
    "airport_origin_lax": (
        LAX, SOFI, None, None,
        {"transit": _transit(800, 1500, 620, boardings=2), "walking": _simple("walking", 7200, 5400),
         "bicycling": _simple("bicycling", 7600, 1700), "driving": _simple("driving", 8200, 900)},
        {"scooter", "bike"}, [],
    ),
    "airport_origin_bur_far": (
        BUR, COLISEUM, None, None,
        {"transit": _transit(400, 3000, 700, boardings=2), "walking": _simple("walking", 25000, 18500),
         "bicycling": _simple("bicycling", 27000, 6000), "driving": _simple("driving", 30000, 2100)},
        set(), [],
    ),
    "preferences_transit_and_walk_only": (
        DTLA, COLISEUM, ["transit", "walk"], None,
        {"transit": _transit(650, 900, 650), "walking": _simple("walking", 6000, 4300),
         "bicycling": _simple("bicycling", 7000, 1500), "driving": _simple("driving", 7000, 1000)},
        {"scooter", "bike"}, [],
    ),
    "preferences_exclude_ridehail": (
        DTLA, COLISEUM, ["transit", "walk", "bike", "scooter", "metro_micro"], None,
        {"transit": _transit(650, 900, 650), "walking": _simple("walking", 4000, 2900),
         "bicycling": _simple("bicycling", 4500, 1000), "driving": _simple("driving", 5000, 800)},
        {"scooter", "bike"}, [],
    ),
    "live_gbfs_pricing": (
        DTLA, COLISEUM, None, None,
        {"transit": _transit(700, 800, 640), "walking": _simple("walking", 3800, 2800),
         "bicycling": _simple("bicycling", 4200, 950), "driving": _simple("driving", 4600, 700)},
        {"scooter", "ebike"}, LIVE_PRICING,
    ),
    "no_transit_route": (
        DTLA, COLISEUM, None, None,
        {"transit": None, "walking": _simple("walking", 3000, 2200),
         "bicycling": _simple("bicycling", 3300, 760), "driving": _simple("driving", 3600, 600)},
        {"bike"}, [],
    ),
    "transit_is_walk_fallback_only": (
        DTLA, COLISEUM, None, None,
        {"transit": {"mode": "transit", "distance_m": 900, "duration_s": 700, "polyline": "W",
                     "steps": [_step("walking", 900, 700, "Walk")]},
         "walking": _simple("walking", 900, 700), "bicycling": _simple("bicycling", 1000, 260),
         "driving": _simple("driving", 1200, 300)},
        {"scooter", "bike"}, [],
    ),
    "equal_time_and_cost_tie_break": (
        DTLA, COLISEUM, None, None,
        {"transit": None, "walking": None,
         "bicycling": _simple("bicycling", 2000, 600), "driving": None},
        set(), [{"plan_id": "ride", "price": 1.0, "per_min_pricing": [{"start": 0, "rate": 0.3, "interval": 1}]}],
    ),
}


def _run(monkeypatch, name):
    origin, destination, preferences, departure_time, directions, micro_types, pricing = SCENARIOS[name]

    def fake_fetch(o, d, mode, departure_time=None, language=None):
        result = directions.get(mode)
        return json.loads(json.dumps(result)) if result is not None else None  # fresh copy per call

    monkeypatch.setattr(route_engine, "_api_key", lambda: "TEST_KEY")
    monkeypatch.setattr(route_engine, "fetch_directions", fake_fetch)
    monkeypatch.setattr(
        route_engine, "_micro_snapshot",
        lambda lat, lng: {"types": set(micro_types), "pricing": list(pricing)},
    )
    return route_engine.optimize(origin, destination, preferences=preferences, departure_time=departure_time)


def _all_results(monkeypatch):
    # Round-trip through JSON so the comparison is on exactly what the API would serialize.
    return {name: json.loads(json.dumps(_run(monkeypatch, name))) for name in SCENARIOS}


def test_snapshot_file_covers_every_scenario():
    assert SNAPSHOT_PATH.exists(), "snapshot missing — see module docstring to (re)generate it"
    assert set(json.loads(SNAPSHOT_PATH.read_text())) == set(SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_ranking_matches_snapshot(monkeypatch, name):
    if os.environ.get("UPDATE_ROUTE_SNAPSHOT"):
        pytest.skip("snapshot is being regenerated")
    expected = json.loads(SNAPSHOT_PATH.read_text())[name]
    actual = json.loads(json.dumps(_run(monkeypatch, name)))
    # Order first — the clearest failure message for the most important property.
    assert [o["id"] for o in actual["options"]] == [o["id"] for o in expected["options"]]
    assert actual == expected


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_same_input_gives_identical_output_every_time(monkeypatch, name):
    first = json.dumps(_run(monkeypatch, name), sort_keys=True)
    for _ in range(3):
        assert json.dumps(_run(monkeypatch, name), sort_keys=True) == first


def test_snapshot_exercises_the_interesting_branches():
    """Guards the snapshot itself: if a scenario stops producing the case it
    was written for, the regression test would be weaker than it looks."""
    snap = json.loads(SNAPSHOT_PATH.read_text())
    ids = {name: [o["id"] for o in result["options"]] for name, result in snap.items()}
    assert any(i.startswith("transit+") for i in ids["central_7km_all_modes"])      # micro access/egress variants
    assert "metro-micro" in ids["airport_origin_lax"]       # both ends in the LAX/Inglewood zone
    assert "metro-micro" not in ids["metro_micro_zone"]      # in-zone but strictly dominated → dropped
    assert "transit" not in ids["no_transit_route"]
    assert "transit" not in ids["transit_is_walk_fallback_only"]
    assert all(set(o["modes"]) <= {"transit", "walk"} for o in snap["preferences_transit_and_walk_only"]["options"])
    assert "rideshare" not in ids["preferences_exclude_ridehail"]
    assert ids["equal_time_and_cost_tie_break"] == ["bike-only", "scooter-only"]     # tie broken by id
    lax = next(o for o in snap["airport_origin_lax"]["options"] if o["id"] == "rideshare")
    assert lax["total_cost_usd"] > 20                                                # includes the LAX pickup fee
    assert snap["two_transfers_long_walks_no_micro_nearby"]["departure_time"] == 1_785_000_000


def test_update_snapshot(monkeypatch):
    """Not a test — the regeneration hook (see module docstring)."""
    if not os.environ.get("UPDATE_ROUTE_SNAPSHOT"):
        pytest.skip("set UPDATE_ROUTE_SNAPSHOT=1 to regenerate")
    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(_all_results(monkeypatch), indent=2, sort_keys=True) + "\n")
