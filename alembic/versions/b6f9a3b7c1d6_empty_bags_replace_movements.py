"""empty_bags (bought into a stockyard, seller + mover) replaces stockyard_empty_bag_movements

Revision ID: b6f9a3b7c1d6
Revises: a5e8f2a6b095
"""
import sqlalchemy as sa
from alembic import op

revision = 'b6f9a3b7c1d6'
down_revision = 'a5e8f2a6b095'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('stockyard_empty_bag_movements')
    op.create_table(
        'empty_bags',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('empty_bags_entry_date', sa.Date(), nullable=False),
        sa.Column('stockyard_id', sa.Integer(), sa.ForeignKey('stockyards.id'), nullable=False),
        sa.Column('grain_id', sa.Integer(), sa.ForeignKey('grains.id'), nullable=False),
        sa.Column('empty_bag_seller_id', sa.Integer(), sa.ForeignKey('empty_bag_sellers.id'), nullable=False),
        sa.Column('empty_bag_mover_id', sa.Integer(), sa.ForeignKey('empty_bag_movers.id'), nullable=False),
        sa.Column('no_of_empty_bags', sa.Integer(), nullable=False),
        sa.Column('business_year', sa.String(7), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_empty_bags_business_year_format'),
        sa.CheckConstraint('no_of_empty_bags > 0', name='ck_empty_bags_no_of_empty_bags'),
    )
    for col in ('business_year', 'stockyard_id', 'grain_id', 'empty_bag_seller_id', 'empty_bag_mover_id'):
        op.create_index(f'ix_empty_bags_{col}', 'empty_bags', [col])


def downgrade() -> None:
    op.drop_table('empty_bags')
    op.create_table(
        'stockyard_empty_bag_movements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('movement_date', sa.Date(), nullable=False),
        sa.Column('stockyard_id', sa.Integer(), sa.ForeignKey('stockyards.id'), nullable=False),
        sa.Column('grain_id', sa.Integer(), sa.ForeignKey('grains.id'), nullable=False),
        sa.Column('movement_type', sa.String(16), nullable=False),
        sa.Column('farmer_id', sa.Integer(), sa.ForeignKey('farmers.id')),
        sa.Column('no_of_bags', sa.Integer(), nullable=False),
        sa.Column('business_year', sa.String(7), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_stockyard_empty_bag_movements_business_year_format'),
        sa.CheckConstraint('no_of_bags > 0', name='ck_stockyard_empty_bag_movements_no_of_bags'),
        sa.CheckConstraint("(movement_type = 'received' AND farmer_id IS NULL) OR (movement_type = 'given_to_farmer' AND farmer_id IS NOT NULL)",
                           name='ck_stockyard_empty_bag_movements_type_farmer'),
    )
    op.create_index('ix_stockyard_empty_bag_movements_business_year', 'stockyard_empty_bag_movements', ['business_year'])
    op.create_index('ix_stockyard_empty_bag_movements_stockyard_id', 'stockyard_empty_bag_movements', ['stockyard_id'])
