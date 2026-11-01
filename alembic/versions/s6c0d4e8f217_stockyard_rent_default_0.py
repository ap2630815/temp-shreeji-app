"""stockyard rent default 0

Revision ID: s6c0d4e8f217
Revises: r5b9c3d7e106
"""
from alembic import op
import sqlalchemy as sa


revision = 's6c0d4e8f217'
down_revision = 'r5b9c3d7e106'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('stockyards', 'rent_of_stockyard', existing_type=sa.Integer(), server_default='0', existing_nullable=False)


def downgrade() -> None:
    op.alter_column('stockyards', 'rent_of_stockyard', existing_type=sa.Integer(), server_default=None, existing_nullable=False)
