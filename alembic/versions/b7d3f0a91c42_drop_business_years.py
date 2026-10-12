"""drop business_years: years close automatically (only the current Oct-Sep year accepts entries)

Revision ID: b7d3f0a91c42
Revises: a1c0de5e7b21
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7d3f0a91c42'
down_revision = 'a1c0de5e7b21'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('business_years')


def downgrade() -> None:
    op.create_table('business_years',
    sa.Column('label', sa.String(length=7), nullable=False),
    sa.Column('is_locked', sa.Boolean(), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('changed_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('label')
    )
