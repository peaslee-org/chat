"""add photogrammetry_jobs.warnings (worker notices shown in the scan view)

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-08-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("photogrammetry_jobs", sa.Column("warnings", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("photogrammetry_jobs", "warnings")
