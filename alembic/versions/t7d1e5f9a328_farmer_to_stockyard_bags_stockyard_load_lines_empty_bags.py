"""farmer to stockyard bags, stockyard load lines, empty bag movements; grain_store_at -> grain_stored_location;
truck load lines may come from a purchase individual

Revision ID: t7d1e5f9a328
Revises: s6c0d4e8f217
"""
from alembic import op
import sqlalchemy as sa


revision = 't7d1e5f9a328'
down_revision = 's6c0d4e8f217'
branch_labels = None
depends_on = None

BUSINESS_YEAR = "^[0-9]{4}-[0-9]{2}$"
ONE_SOURCE = ("(purchase_farmer_entry_id IS NOT NULL AND purchase_individual_id IS NULL) OR "
              "(purchase_farmer_entry_id IS NULL AND purchase_individual_id IS NOT NULL)")


def _stamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)]


def upgrade() -> None:
    # ---- grain_store_at -> grain_stored_location
    op.alter_column('purchase_farmers_entries', 'grain_store_at', new_column_name='grain_stored_location')
    op.alter_column('purchase_individuals', 'grain_store_at', new_column_name='grain_stored_location')

    # ---- a load line comes from a purchase_farmers_entries row OR a purchase_individuals row
    op.alter_column('truck_load_lines', 'purchase_farmer_entry_id', existing_type=sa.Integer(), nullable=True)
    op.add_column('truck_load_lines', sa.Column('purchase_individual_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_truck_load_lines_purchase_individual_id', 'truck_load_lines', 'purchase_individuals', ['purchase_individual_id'], ['id'])
    op.create_index('ix_truck_load_lines_purchase_individual_id', 'truck_load_lines', ['purchase_individual_id'])
    op.create_unique_constraint('uq_truck_load_lines_trip_individual', 'truck_load_lines', ['trip_id', 'purchase_individual_id'])
    op.create_check_constraint('ck_truck_load_lines_one_source', 'truck_load_lines', ONE_SOURCE)

    # ---- grains: the expected raw weight per bag (kg); stockyard load lines start from it. Existing grains start at their net bag weight.
    op.add_column('grains', sa.Column('expected_raw_weight_per_bag', sa.Float(), nullable=True))
    op.execute('UPDATE grains SET expected_raw_weight_per_bag = net_bag_weight')
    op.alter_column('grains', 'expected_raw_weight_per_bag', existing_type=sa.Float(), nullable=False)

    # ---- stockyard load lines
    op.create_table(
        'stockyard_load_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('stockyard_id', sa.Integer(), nullable=False),
        sa.Column('grain_id', sa.Integer(), nullable=False),
        sa.Column('no_of_loaded_bags', sa.Integer(), nullable=False),
        sa.Column('expected_raw_weight_per_bag', sa.Float(), nullable=False),
        sa.CheckConstraint('no_of_loaded_bags > 0', name='ck_stockyard_load_lines_no_of_loaded_bags'),
        sa.CheckConstraint('expected_raw_weight_per_bag >= 0', name='ck_stockyard_load_lines_expected_raw_weight_per_bag'),
        sa.ForeignKeyConstraint(['trip_id'], ['truck_trips.id']),
        sa.ForeignKeyConstraint(['stockyard_id'], ['stockyards.id']),
        sa.ForeignKeyConstraint(['grain_id'], ['grains.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trip_id', 'stockyard_id', name='uq_stockyard_load_lines_trip_stockyard'),
    )
    op.create_index('ix_stockyard_load_lines_stockyard_id', 'stockyard_load_lines', ['stockyard_id'])

    # ---- farmer -> stockyard
    op.create_table(
        'farmer_stockyard_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transfer_date', sa.Date(), nullable=False),
        sa.Column('purchase_farmer_entry_id', sa.Integer(), nullable=True),
        sa.Column('purchase_individual_id', sa.Integer(), nullable=True),
        sa.Column('stockyard_id', sa.Integer(), nullable=False),
        sa.Column('no_of_bags', sa.Integer(), nullable=False),
        sa.Column('business_year', sa.String(length=7), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"business_year ~ '{BUSINESS_YEAR}'", name='ck_farmer_stockyard_transfers_business_year_format'),
        sa.CheckConstraint('no_of_bags > 0', name='ck_farmer_stockyard_transfers_no_of_bags'),
        sa.CheckConstraint(ONE_SOURCE, name='ck_farmer_stockyard_transfers_one_source'),
        sa.ForeignKeyConstraint(['purchase_farmer_entry_id'], ['purchase_farmers_entries.id']),
        sa.ForeignKeyConstraint(['purchase_individual_id'], ['purchase_individuals.id']),
        sa.ForeignKeyConstraint(['stockyard_id'], ['stockyards.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_farmer_stockyard_transfers_business_year', 'farmer_stockyard_transfers', ['business_year'])
    op.create_index('ix_farmer_stockyard_transfers_purchase_farmer_entry_id', 'farmer_stockyard_transfers', ['purchase_farmer_entry_id'])
    op.create_index('ix_farmer_stockyard_transfers_purchase_individual_id', 'farmer_stockyard_transfers', ['purchase_individual_id'])
    op.create_index('ix_farmer_stockyard_transfers_stockyard_id', 'farmer_stockyard_transfers', ['stockyard_id'])

    # ---- empty bags received into / given out of a stockyard
    op.create_table(
        'stockyard_empty_bag_movements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('movement_date', sa.Date(), nullable=False),
        sa.Column('stockyard_id', sa.Integer(), nullable=False),
        sa.Column('grain_id', sa.Integer(), nullable=False),
        sa.Column('movement_type', sa.String(length=16), nullable=False),
        sa.Column('farmer_id', sa.Integer(), nullable=True),
        sa.Column('no_of_bags', sa.Integer(), nullable=False),
        sa.Column('business_year', sa.String(length=7), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"business_year ~ '{BUSINESS_YEAR}'", name='ck_stockyard_empty_bag_movements_business_year_format'),
        sa.CheckConstraint('no_of_bags > 0', name='ck_stockyard_empty_bag_movements_no_of_bags'),
        sa.CheckConstraint("(movement_type = 'received' AND farmer_id IS NULL) OR (movement_type = 'given_to_farmer' AND farmer_id IS NOT NULL)",
                           name='ck_stockyard_empty_bag_movements_type_farmer'),
        sa.ForeignKeyConstraint(['stockyard_id'], ['stockyards.id']),
        sa.ForeignKeyConstraint(['grain_id'], ['grains.id']),
        sa.ForeignKeyConstraint(['farmer_id'], ['farmers.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_stockyard_empty_bag_movements_business_year', 'stockyard_empty_bag_movements', ['business_year'])
    op.create_index('ix_stockyard_empty_bag_movements_stockyard_id', 'stockyard_empty_bag_movements', ['stockyard_id'])


def downgrade() -> None:
    op.drop_table('stockyard_empty_bag_movements')
    op.drop_table('farmer_stockyard_transfers')
    op.drop_table('stockyard_load_lines')
    op.execute('ALTER TABLE grains DROP COLUMN IF EXISTS expected_raw_weight_per_bag')
    op.drop_constraint('ck_truck_load_lines_one_source', 'truck_load_lines', type_='check')
    op.drop_constraint('uq_truck_load_lines_trip_individual', 'truck_load_lines', type_='unique')
    op.drop_index('ix_truck_load_lines_purchase_individual_id', table_name='truck_load_lines')
    op.drop_constraint('fk_truck_load_lines_purchase_individual_id', 'truck_load_lines', type_='foreignkey')
    op.drop_column('truck_load_lines', 'purchase_individual_id')
    op.alter_column('truck_load_lines', 'purchase_farmer_entry_id', existing_type=sa.Integer(), nullable=False)
    op.alter_column('purchase_individuals', 'grain_stored_location', new_column_name='grain_store_at')
    op.alter_column('purchase_farmers_entries', 'grain_stored_location', new_column_name='grain_store_at')
