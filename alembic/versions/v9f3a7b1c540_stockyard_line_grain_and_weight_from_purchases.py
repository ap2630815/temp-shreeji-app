"""stockyard_truck_load_lines: drop grain_id and expected_raw_weight_per_bag; stockyard_purchase_entries: add expected_raw_weight_per_bag

The grain of a stockyard load line is the grain of its trip's booking, and its expected raw weight per bag is worked out from the
purchases that filled the stockyard, so the line stores neither. Every stockyard purchase entry now carries its own expected raw
weight per bag (starting at the grain's value, editable), like the farmer purchases do.

Revision ID: v9f3a7b1c540
Revises: u8e2f6a0b439
"""
import sqlalchemy as sa
from alembic import op


revision = 'v9f3a7b1c540'
down_revision = 'u8e2f6a0b439'
branch_labels = None
depends_on = None

TRIP_GRAIN = """(SELECT b.grain_id FROM truck_trips t JOIN broker_bookings bb ON bb.id = t.broker_booking_id
                 JOIN brokerages b ON b.id = bb.brokerage_id WHERE t.id = stockyard_truck_load_lines.trip_id)"""


def upgrade() -> None:
    op.add_column('stockyard_purchase_entries', sa.Column('expected_raw_weight_per_bag', sa.Float(), nullable=True))
    op.execute("""UPDATE stockyard_purchase_entries e SET expected_raw_weight_per_bag = g.expected_raw_weight_per_bag
                  FROM stockyard_purchases p JOIN grains g ON g.id = p.grain_id WHERE p.id = e.stockyard_purchase_id""")
    op.alter_column('stockyard_purchase_entries', 'expected_raw_weight_per_bag', existing_type=sa.Float(), nullable=False)
    op.create_check_constraint('ck_stockyard_purchase_entries_expected_raw_weight_per_bag', 'stockyard_purchase_entries', 'expected_raw_weight_per_bag >= 0')
    op.drop_constraint('ck_stockyard_truck_load_lines_expected_raw_weight_per_bag', 'stockyard_truck_load_lines', type_='check')
    op.drop_column('stockyard_truck_load_lines', 'expected_raw_weight_per_bag')
    op.drop_column('stockyard_truck_load_lines', 'grain_id')


def downgrade() -> None:
    op.add_column('stockyard_truck_load_lines', sa.Column('grain_id', sa.Integer(), nullable=True))
    op.execute(f"UPDATE stockyard_truck_load_lines SET grain_id = {TRIP_GRAIN}")
    op.alter_column('stockyard_truck_load_lines', 'grain_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key('stockyard_truck_load_lines_grain_id_fkey', 'stockyard_truck_load_lines', 'grains', ['grain_id'], ['id'])
    op.add_column('stockyard_truck_load_lines', sa.Column('expected_raw_weight_per_bag', sa.Float(), nullable=True))
    op.execute("UPDATE stockyard_truck_load_lines SET expected_raw_weight_per_bag = (SELECT expected_raw_weight_per_bag FROM grains WHERE id = grain_id)")
    op.alter_column('stockyard_truck_load_lines', 'expected_raw_weight_per_bag', existing_type=sa.Float(), nullable=False)
    op.create_check_constraint('ck_stockyard_truck_load_lines_expected_raw_weight_per_bag', 'stockyard_truck_load_lines', 'expected_raw_weight_per_bag >= 0')
    op.drop_constraint('ck_stockyard_purchase_entries_expected_raw_weight_per_bag', 'stockyard_purchase_entries', type_='check')
    op.drop_column('stockyard_purchase_entries', 'expected_raw_weight_per_bag')
