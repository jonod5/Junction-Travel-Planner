"""Add trip.access_token — a per-trip capability token (audit SEC-02).

Trips are anonymous, and until now any caller could read, edit or delete any
trip by its sequential integer id. POST /api/trips now generates a random
token; every other /api/trips route requires it in the X-Trip-Token header.

Existing rows keep access_token NULL and become unreachable over the API.
That is intended: a trip is the planner's working state for one browser
session and is never reloaded by id (saved plans are itinerary rows, which
store their own snapshot), so no user-visible data is lost.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trip", sa.Column("access_token", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("trip", "access_token")
