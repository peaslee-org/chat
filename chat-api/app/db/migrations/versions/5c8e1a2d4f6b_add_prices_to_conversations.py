"""add prices to conversations

Revision ID: 5c8e1a2d4f6b
Revises: 3a1f2b4c8d9e
Create Date: 2026-03-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '5c8e1a2d4f6b'
down_revision: Union[str, None] = '3a1f2b4c8d9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('input_price_per_1k_tokens', sa.Float(), nullable=True))
    op.add_column('conversations', sa.Column('output_price_per_1k_tokens', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'output_price_per_1k_tokens')
    op.drop_column('conversations', 'input_price_per_1k_tokens')
