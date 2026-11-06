"""rename bag_suppliers -> empty_bag_sellers

Revision ID: y3c6d0e4f873
Revises: x2b5c9d3e762
"""
from alembic import op

revision = 'y3c6d0e4f873'
down_revision = 'x2b5c9d3e762'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table('bag_suppliers', 'empty_bag_sellers')
    op.execute("ALTER SEQUENCE IF EXISTS bag_suppliers_id_seq RENAME TO empty_bag_sellers_id_seq")
    op.execute("ALTER INDEX IF EXISTS bag_suppliers_pkey RENAME TO empty_bag_sellers_pkey")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS empty_bag_sellers_pkey RENAME TO bag_suppliers_pkey")
    op.execute("ALTER SEQUENCE IF EXISTS empty_bag_sellers_id_seq RENAME TO bag_suppliers_id_seq")
    op.rename_table('empty_bag_sellers', 'bag_suppliers')
