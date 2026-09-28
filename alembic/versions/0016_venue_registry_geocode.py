"""Add venue-level registry fields for geocoded venues (v1.7).

Adds external_ref (a stable slug, e.g. "intuit-dome") and source to venue.
The 6 hand-collected venues get neither — external_ref IS NULL is what
marks a venue as hand-collected/pre-pipeline, same convention
transit_access.external_ref already uses. A geocoded venue's source is
"geocoded" (see app/services/geocode.py); Venue.confidence (already added
in migration 0012) carries the geocode precision label.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("venue", sa.Column("external_ref", sa.String(100), nullable=True))
    op.add_column("venue", sa.Column("source", sa.String(50), nullable=True))
    op.create_index("ix_venue_external_ref", "venue", ["external_ref"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_venue_external_ref", table_name="venue")
    op.drop_column("venue", "source")
    op.drop_column("venue", "external_ref")
