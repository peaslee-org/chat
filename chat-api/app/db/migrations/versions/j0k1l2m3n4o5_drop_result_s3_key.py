"""drop result_s3_key from transcription_jobs

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-19 00:00:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("transcription_jobs", "result_s3_key")


def downgrade() -> None:
    op.add_column(
        "transcription_jobs",
        sa.Column("result_s3_key", sa.String(length=1024), nullable=True),
    )
