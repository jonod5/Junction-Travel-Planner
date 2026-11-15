"""
Pydantic schemas for saved itineraries — /api/itineraries.

Kept in a separate file rather than growing app/schemas.py, which already
flagged its own "split past ~10 models" threshold in its docstring.

Design choices:
- saved_plan is an untyped dict — its shape is owned by the frontend (see
  frontend/lib/store.tsx's TripContext: ordered stops + the selected
  RouteOption per leg). The backend stores and returns it verbatim rather
  than re-validating internals, so the route engine's option shape can keep
  evolving without a backend migration.
- ItineraryUpdate uses exclude_unset semantics in the router (all fields
  optional, no defaults meaningfully distinguishable from "not sent") so a
  PATCH can tell "field omitted" apart from "field explicitly set to null"
  (e.g. clearing trip_date).
"""

import json
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ItineraryTag.name is String(50); a longer tag would 500 on Postgres.
Tag = Annotated[str, Field(max_length=50)]
MAX_TAGS = 20
# saved_plan is opaque to the backend, so its only possible bound is size.
# A real plan (a handful of legs, each with its selected option's steps and
# polylines) serializes to tens of KB; 1 MB is far above that and still stops
# the column being used as free storage.
MAX_SAVED_PLAN_BYTES = 1_000_000


def _check_plan_size(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if plan is not None and len(json.dumps(plan, separators=(",", ":"))) > MAX_SAVED_PLAN_BYTES:
        raise ValueError(f"saved_plan is larger than {MAX_SAVED_PLAN_BYTES} bytes")
    return plan


class ItineraryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    trip_date: date | None = None
    is_pinned: bool = False
    tags: list[Tag] = Field(default_factory=list, max_length=MAX_TAGS)
    saved_plan: dict[str, Any] = {}

    _plan_size = field_validator("saved_plan")(_check_plan_size)


class ItineraryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    trip_date: date | None = None
    is_pinned: bool | None = None
    tags: list[Tag] | None = Field(None, max_length=MAX_TAGS)
    saved_plan: dict[str, Any] | None = None

    _plan_size = field_validator("saved_plan")(_check_plan_size)


class ItineraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    trip_date: date | None
    is_pinned: bool
    saved_plan: dict[str, Any]
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class ItineraryListOut(BaseModel):
    items: list[ItineraryOut]
    total: int
    limit: int
    offset: int
