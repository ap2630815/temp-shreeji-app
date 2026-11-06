"""bag_supplies -> empty_bag_seller_entries, bag_mover_entries -> empty_bag_mover_entries (+ spec column names)

Revision ID: a5e8f2a6b095
Revises: z4d7e1f5a984
"""
from alembic import op

revision = 'a5e8f2a6b095'
down_revision = 'z4d7e1f5a984'
branch_labels = None
depends_on = None

# (old table, new table, [(old col, new col)], [(old index, new index)], [(old check, new check)])
RENAMES = (
    ('bag_supplies', 'empty_bag_seller_entries',
     [('supplier_id', 'empty_bag_seller_id'), ('supply_date', 'selling_date'), ('no_of_bags', 'no_of_empty_bags')],
     [('ix_bag_supplies_business_year', 'ix_empty_bag_seller_entries_business_year'),
      ('ix_bag_supplies_farmer_id', 'ix_empty_bag_seller_entries_farmer_id'),
      ('ix_bag_supplies_supplier_id', 'ix_empty_bag_seller_entries_empty_bag_seller_id')],
     [('ck_bag_supplies_business_year_format', 'ck_empty_bag_seller_entries_business_year_format'),
      ('ck_bag_supplies_positive', 'ck_empty_bag_seller_entries_positive')]),
    ('bag_mover_entries', 'empty_bag_mover_entries',
     [('mover_id', 'empty_bag_mover_id')],
     [('ix_bag_mover_entries_business_year', 'ix_empty_bag_mover_entries_business_year'),
      ('ix_bag_mover_entries_farmer_id', 'ix_empty_bag_mover_entries_farmer_id'),
      ('ix_bag_mover_entries_mover_id', 'ix_empty_bag_mover_entries_empty_bag_mover_id')],
     [('ck_bag_mover_entries_business_year_format', 'ck_empty_bag_mover_entries_business_year_format'),
      ('ck_bag_mover_entries_positive', 'ck_empty_bag_mover_entries_positive')]),
)


def _apply(forward: bool) -> None:
    for old, new, cols, idx, checks in RENAMES:
        a, b = (old, new) if forward else (new, old)
        op.rename_table(a, b)
        op.execute(f"ALTER SEQUENCE IF EXISTS {a}_id_seq RENAME TO {b}_id_seq")
        op.execute(f"ALTER INDEX IF EXISTS {a}_pkey RENAME TO {b}_pkey")
        for co, cn in cols:
            op.alter_column(b, co if forward else cn, new_column_name=cn if forward else co)
        for io, i_n in idx:
            op.execute(f"ALTER INDEX IF EXISTS {io if forward else i_n} RENAME TO {i_n if forward else io}")
        for co, cn in checks:
            op.execute(f"ALTER TABLE {b} RENAME CONSTRAINT {co if forward else cn} TO {cn if forward else co}")


def upgrade() -> None:
    _apply(True)


def downgrade() -> None:
    _apply(False)
