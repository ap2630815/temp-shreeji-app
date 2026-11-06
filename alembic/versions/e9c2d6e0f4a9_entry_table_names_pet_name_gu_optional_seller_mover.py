"""empty_bag_seller_entries -> empty_bag_sellers_entries, empty_bag_mover_entries -> empty_bag_movers_entries (file4 names);
pet_name_gu + unique pet_name on the empty bag seller / mover masters (file1); empty_bags seller and mover become optional

Revision ID: e9c2d6e0f4a9
Revises: d8b1c5d9e3f8
"""
import sqlalchemy as sa
from alembic import op

revision = 'e9c2d6e0f4a9'
down_revision = 'd8b1c5d9e3f8'
branch_labels = None
depends_on = None

TABLES = (
    ('empty_bag_seller_entries', 'empty_bag_sellers_entries', 'empty_bag_sellers',
     ['business_year', 'farmer_id', 'empty_bag_seller_id'], ['business_year_format', 'positive']),
    ('empty_bag_mover_entries', 'empty_bag_movers_entries', 'empty_bag_movers',
     ['business_year', 'farmer_id', 'empty_bag_mover_id'], ['business_year_format', 'positive']),
)


def _rename(forward: bool) -> None:
    for old, new, prefix, indexes, checks in TABLES:
        a, b = (old, new) if forward else (new, old)
        op.rename_table(a, b)
        op.execute(f"ALTER SEQUENCE IF EXISTS {a}_id_seq RENAME TO {b}_id_seq")
        op.execute(f"ALTER INDEX IF EXISTS {a}_pkey RENAME TO {b}_pkey")
        old_prefix = old
        for ix in indexes:
            src, dst = f"ix_{old_prefix}_{ix}", f"ix_{prefix}_{ix}"
            op.execute(f"ALTER INDEX IF EXISTS {src if forward else dst} RENAME TO {dst if forward else src}")
        for ck in checks:
            src, dst = f"ck_{old_prefix}_{ck}", f"ck_{prefix}_{ck}"
            op.execute(f"ALTER TABLE {b} RENAME CONSTRAINT {src if forward else dst} TO {dst if forward else src}")


def upgrade() -> None:
    _rename(True)
    for table in ('empty_bag_sellers', 'empty_bag_movers'):
        op.add_column(table, sa.Column('pet_name_gu', sa.String(30)))
    op.create_unique_constraint('empty_bag_sellers_pet_name_key', 'empty_bag_sellers', ['pet_name'])
    op.alter_column('empty_bags', 'empty_bag_seller_id', existing_type=sa.Integer(), nullable=True)
    op.alter_column('empty_bags', 'empty_bag_mover_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column('empty_bags', 'empty_bag_mover_id', existing_type=sa.Integer(), nullable=False)
    op.alter_column('empty_bags', 'empty_bag_seller_id', existing_type=sa.Integer(), nullable=False)
    op.drop_constraint('empty_bag_sellers_pet_name_key', 'empty_bag_sellers', type_='unique')
    for table in ('empty_bag_movers', 'empty_bag_sellers'):
        op.drop_column(table, 'pet_name_gu')
    _rename(False)
