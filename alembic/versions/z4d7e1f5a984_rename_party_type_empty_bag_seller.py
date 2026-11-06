"""payments: party_type / payable_type 'bag_supplier' -> 'empty_bag_seller'

Revision ID: z4d7e1f5a984
Revises: y3c6d0e4f873
"""
from alembic import op

revision = 'z4d7e1f5a984'
down_revision = 'y3c6d0e4f873'
branch_labels = None
depends_on = None

PAY = "party_type IN ('farmer', 'truck', 'labour_group', '{}', 'broker')"
ALLOC = "payable_type IN ('farmer', 'purchase_individual', 'truck', 'labour_group', '{}', 'broker')"


def _swap(old: str, new: str) -> None:
    op.drop_constraint('ck_payments_party_type', 'payments', type_='check')
    op.drop_constraint('ck_alloc_payable_type', 'payment_allocations', type_='check')
    op.execute(f"UPDATE payments SET party_type = '{new}' WHERE party_type = '{old}'")
    op.execute(f"UPDATE payment_allocations SET payable_type = '{new}' WHERE payable_type = '{old}'")
    op.create_check_constraint('ck_payments_party_type', 'payments', PAY.format(new))
    op.create_check_constraint('ck_alloc_payable_type', 'payment_allocations', ALLOC.format(new))


def upgrade() -> None:
    _swap('bag_supplier', 'empty_bag_seller')


def downgrade() -> None:
    _swap('empty_bag_seller', 'bag_supplier')
