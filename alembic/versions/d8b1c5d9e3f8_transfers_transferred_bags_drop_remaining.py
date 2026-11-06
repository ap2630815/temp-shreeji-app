"""farmer_to_stockyard_transfers.no_of_bags -> no_of_transferred_bags; farmers_truck_load_lines.total_remaining_bags is no longer stored

Revision ID: d8b1c5d9e3f8
Revises: c7a0b4c8d2e7
"""
import sqlalchemy as sa
from alembic import op

revision = 'd8b1c5d9e3f8'
down_revision = 'c7a0b4c8d2e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table('farmer_stockyard_transfers', 'farmer_to_stockyard_transfers')
    op.execute("ALTER SEQUENCE IF EXISTS farmer_stockyard_transfers_id_seq RENAME TO farmer_to_stockyard_transfers_id_seq")
    op.execute("ALTER INDEX IF EXISTS farmer_stockyard_transfers_pkey RENAME TO farmer_to_stockyard_transfers_pkey")
    op.drop_constraint('ck_farmer_stockyard_transfers_no_of_bags', 'farmer_to_stockyard_transfers', type_='check')
    op.alter_column('farmer_to_stockyard_transfers', 'no_of_bags', new_column_name='no_of_transferred_bags')
    op.create_check_constraint('ck_farmer_stockyard_transfers_no_of_bags', 'farmer_to_stockyard_transfers', 'no_of_transferred_bags > 0')
    op.drop_constraint('ck_farmers_truck_load_lines_total_remaining_bags', 'farmers_truck_load_lines', type_='check')
    op.drop_column('farmers_truck_load_lines', 'total_remaining_bags')


def downgrade() -> None:
    op.add_column('farmers_truck_load_lines', sa.Column('total_remaining_bags', sa.Integer(), nullable=False, server_default='0'))
    op.execute(
        "UPDATE farmers_truck_load_lines l SET total_remaining_bags = GREATEST(COALESCE((SELECT total_available_bags FROM purchase_farmers_entries WHERE id = l.purchase_farmer_entry_id),"
        " (SELECT total_available_bags FROM purchase_individuals WHERE id = l.purchase_individual_id), 0)"
        " - COALESCE((SELECT SUM(no_of_transferred_bags) FROM farmer_to_stockyard_transfers t WHERE t.purchase_farmer_entry_id = l.purchase_farmer_entry_id OR t.purchase_individual_id = l.purchase_individual_id), 0)"
        " - COALESCE((SELECT SUM(no_of_loaded_bags) FROM farmers_truck_load_lines o WHERE (o.purchase_farmer_entry_id = l.purchase_farmer_entry_id OR o.purchase_individual_id = l.purchase_individual_id) AND o.id <= l.id), 0), 0)")
    op.alter_column('farmers_truck_load_lines', 'total_remaining_bags', server_default=None)
    op.create_check_constraint('ck_farmers_truck_load_lines_total_remaining_bags', 'farmers_truck_load_lines', 'total_remaining_bags >= 0')
    op.drop_constraint('ck_farmer_stockyard_transfers_no_of_bags', 'farmer_to_stockyard_transfers', type_='check')
    op.alter_column('farmer_to_stockyard_transfers', 'no_of_transferred_bags', new_column_name='no_of_bags')
    op.create_check_constraint('ck_farmer_stockyard_transfers_no_of_bags', 'farmer_to_stockyard_transfers', 'no_of_bags > 0')
    op.execute("ALTER INDEX IF EXISTS farmer_to_stockyard_transfers_pkey RENAME TO farmer_stockyard_transfers_pkey")
    op.execute("ALTER SEQUENCE IF EXISTS farmer_to_stockyard_transfers_id_seq RENAME TO farmer_stockyard_transfers_id_seq")
    op.rename_table('farmer_to_stockyard_transfers', 'farmer_stockyard_transfers')
