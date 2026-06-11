"""add model_id to conversations

Revision ID: 3a1f2b4c8d9e
Revises: ece77fd9c298
Create Date: 2026-03-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '3a1f2b4c8d9e'
down_revision: Union[str, None] = 'ece77fd9c298'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations',
        sa.Column('model_id', sa.String(length=256), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('conversations', 'model_id')
