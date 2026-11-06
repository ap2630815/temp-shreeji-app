"""empty_bag_movers master and bag_mover_entries (the movers tab of /BagSuppliers)

Revision ID: x2b5c9d3e762
Revises: w1a4b8c2d651
"""
import sqlalchemy as sa
from alembic import op

revision = 'x2b5c9d3e762'
down_revision = 'w1a4b8c2d651'
branch_labels = None
depends_on = None


def upgrade() -> None:
    ts = lambda: sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)
    op.create_table(
        'empty_bag_movers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('name_gu', sa.String(120)),
        sa.Column('pet_name', sa.String(30), nullable=False, unique=True),
        sa.Column('mobile', sa.String(10), nullable=False, unique=True),
        sa.Column('upi_number', sa.String(10), unique=True),
        sa.Column('description', sa.Text()),
        ts(),
        sa.CheckConstraint("mobile ~ '^[0-9]{10}$'", name='ck_mobile_10_digits'),
        sa.CheckConstraint("upi_number IS NULL OR upi_number ~ '^[0-9]{10}$'", name='ck_upi_number_10_digits'),
    )
    op.create_table(
        'bag_mover_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('mover_id', sa.Integer(), sa.ForeignKey('empty_bag_movers.id'), nullable=False),
        sa.Column('farmer_id', sa.Integer(), sa.ForeignKey('farmers.id'), nullable=False),
        sa.Column('mover_date', sa.Date(), nullable=False),
        sa.Column('cost_per_mover', sa.Integer(), nullable=False),
        sa.Column('no_of_empty_bags', sa.Integer(), nullable=False),
        sa.Column('business_year', sa.String(7), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id')),
        ts(),
        sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_bag_mover_entries_business_year_format'),
        sa.CheckConstraint('cost_per_mover > 0 AND no_of_empty_bags > 0', name='ck_bag_mover_entries_positive'),
    )
    op.create_index('ix_bag_mover_entries_business_year', 'bag_mover_entries', ['business_year'])
    op.create_index('ix_bag_mover_entries_farmer_id', 'bag_mover_entries', ['farmer_id'])
    op.create_index('ix_bag_mover_entries_mover_id', 'bag_mover_entries', ['mover_id'])


def downgrade() -> None:
    op.drop_table('bag_mover_entries')
    op.drop_table('empty_bag_movers')
