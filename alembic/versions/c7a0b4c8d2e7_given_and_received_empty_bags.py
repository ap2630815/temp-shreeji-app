"""stockyard_purchases.no_of_empty_bags -> no_of_given_empty_bags; stockyard_purchase_entries.no_of_received_empty_bags

Existing entries get their received bags worked out purchase by purchase, in id order:
    received = given - filled so far (this entry included) - received by the earlier entries   (never below 0)

Revision ID: c7a0b4c8d2e7
Revises: b6f9a3b7c1d6
"""
import sqlalchemy as sa
from alembic import op

revision = 'c7a0b4c8d2e7'
down_revision = 'b6f9a3b7c1d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_stockyard_purchases_no_of_empty_bags', 'stockyard_purchases', type_='check')
    op.alter_column('stockyard_purchases', 'no_of_empty_bags', new_column_name='no_of_given_empty_bags')
    op.create_check_constraint('ck_stockyard_purchases_no_of_given_empty_bags', 'stockyard_purchases', 'no_of_given_empty_bags >= 0')
    op.add_column('stockyard_purchase_entries', sa.Column('no_of_received_empty_bags', sa.Integer(), nullable=False, server_default='0'))
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT e.id, e.stockyard_purchase_id, e.no_of_filled_bags, p.no_of_given_empty_bags FROM stockyard_purchase_entries e "
        "JOIN stockyard_purchases p ON p.id = e.stockyard_purchase_id ORDER BY e.stockyard_purchase_id, e.id")).all()
    filled = received = 0
    last = None
    for entry_id, purchase_id, entry_filled, given in rows:
        if purchase_id != last:
            filled = received = 0
            last = purchase_id
        filled += entry_filled
        value = max(0, given - filled - received)
        received += value
        bind.execute(sa.text("UPDATE stockyard_purchase_entries SET no_of_received_empty_bags = :v WHERE id = :i"), {'v': value, 'i': entry_id})
    op.create_check_constraint('ck_stockyard_purchase_entries_no_of_received_empty_bags', 'stockyard_purchase_entries', 'no_of_received_empty_bags >= 0')


def downgrade() -> None:
    op.drop_constraint('ck_stockyard_purchase_entries_no_of_received_empty_bags', 'stockyard_purchase_entries', type_='check')
    op.drop_column('stockyard_purchase_entries', 'no_of_received_empty_bags')
    op.drop_constraint('ck_stockyard_purchases_no_of_given_empty_bags', 'stockyard_purchases', type_='check')
    op.alter_column('stockyard_purchases', 'no_of_given_empty_bags', new_column_name='no_of_empty_bags')
    op.create_check_constraint('ck_stockyard_purchases_no_of_empty_bags', 'stockyard_purchases', 'no_of_empty_bags >= 0')
