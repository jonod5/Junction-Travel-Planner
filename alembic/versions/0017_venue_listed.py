"""Add venue.listed so out-of-scope venues can be hidden from the app (v1.7b).

The v1.7 registry added 27 venues, but the intended scope was the LA
Metro-served core. `listed` controls only whether a venue appears in
GET /api/venues — nothing is deleted, GET /api/venues/{id} still serves a
hidden venue, and the enrichment pipeline still sees it. The data step hides
the 18 venues outside Metro's service area (Long Beach, Carson, and the
remaining out-of-area sites). Un-hide one by setting listed = true once its
agency's GTFS feed is ingested (see docs/known-gaps.md).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HIDDEN_REFS = (
    # Long Beach
    "alamitos-beach-stadium",
    "long-beach-aquatics-center",
    "long-beach-arena",
    "long-beach-climbing-theater",
    "long-beach-target-shooting-hall",
    "marine-stadium",
    "belmont-shore",
    # Carson
    "carson-stadium",
    "carson-velodrome",
    "carson-courts",
    "carson-field",
    # Other
    "riviera-country-club",
    "port-of-los-angeles",
    "whittier-narrows-shooting",
    "industry-hills-mtb",
    "honda-center",
    "fairgrounds-cricket-stadium",
    "trestles-state-beach",
)


def upgrade() -> None:
    op.add_column(
        "venue",
        sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    venue = sa.table("venue", sa.column("external_ref", sa.String), sa.column("listed", sa.Boolean))
    op.execute(venue.update().where(venue.c.external_ref.in_(HIDDEN_REFS)).values(listed=False))


def downgrade() -> None:
    op.drop_column("venue", "listed")
