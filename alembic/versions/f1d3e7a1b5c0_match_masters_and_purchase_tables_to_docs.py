"""Match the application to the docs (file1, file2, file4):
  transporters.pet_name_gu (NOT NULL);
  industries: industrialist_name(_gu) -> industry_name(_gu), owner_name/owner_mobile -> industry_owner_name/industry_owner_mobile;
  farmers: private_note_owner_only (the old owner-only 'description'), description (the old 'public_figure'), public_figure dropped;
  labour_group_wages.other_expenses -> other_rate;
  purchase_group -> purchase_groups, purchase_group_farmers -> purchase_group_add_farmers, purchase_farmers_entries -> purchase_group_farmers_entries

Revision ID: f1d3e7a1b5c0
Revises: e9c2d6e0f4a9
"""
import sqlalchemy as sa
from alembic import op

revision = 'f1d3e7a1b5c0'
down_revision = 'e9c2d6e0f4a9'
branch_labels = None
depends_on = None

# (old table, new table, [(old constraint, new constraint)], [(old index, new index)])
PURCHASE_TABLES = (
    ('purchase_group', 'purchase_groups', [], []),
    ('purchase_group_farmers', 'purchase_group_add_farmers',
     [('uq_purchase_group_farmers_info_farmer', 'uq_purchase_group_add_farmers_info_farmer')],
     [('ix_purchase_group_farmers_farmer_id', 'ix_purchase_group_add_farmers_farmer_id')]),
    ('purchase_farmers_entries', 'purchase_group_farmers_entries',
     [(f'ck_purchase_farmers_entries_{n}', f'ck_purchase_group_farmers_entries_{n}') for n in
      ('borrowed_amount', 'borrowed_amount_le_payable_amount', 'business_year_format', 'expected_raw_weight_per_bag', 'extra_kilos',
       'no_of_filled_bags', 'no_of_handful_bags', 'payable_amount', 'total_available_bags')]
     + [('fk_purchase_farmers_entries_listed_farmer', 'fk_purchase_group_farmers_entries_listed_farmer')],
     [(f'ix_purchase_farmers_entries_{n}', f'ix_purchase_group_farmers_entries_{n}') for n in ('business_year', 'farmer_id', 'labour_group_id', 'purchase_group_id')]),
)


def _purchase_tables(forward: bool) -> None:
    for old, new, constraints, indexes in PURCHASE_TABLES:
        a, b = (old, new) if forward else (new, old)
        op.rename_table(a, b)
        op.execute(f"ALTER SEQUENCE IF EXISTS {a}_id_seq RENAME TO {b}_id_seq")
        op.execute(f"ALTER INDEX IF EXISTS {a}_pkey RENAME TO {b}_pkey")
        for o, n in constraints:
            src, dst = (o, n) if forward else (n, o)
            op.execute(f"ALTER TABLE {b} RENAME CONSTRAINT {src} TO {dst}")
        for o, n in indexes:
            src, dst = (o, n) if forward else (n, o)
            op.execute(f"ALTER INDEX IF EXISTS {src} RENAME TO {dst}")


def upgrade() -> None:
    op.add_column('transporters', sa.Column('pet_name_gu', sa.String(30)))
    op.execute("UPDATE transporters SET pet_name_gu = pet_name")
    op.alter_column('transporters', 'pet_name_gu', existing_type=sa.String(30), nullable=False)

    op.alter_column('industries', 'industrialist_name', new_column_name='industry_name')
    op.alter_column('industries', 'industrialist_name_gu', new_column_name='industry_name_gu')
    op.alter_column('industries', 'owner_name', new_column_name='industry_owner_name')
    op.alter_column('industries', 'owner_mobile', new_column_name='industry_owner_mobile')

    op.add_column('farmers', sa.Column('private_note_owner_only', sa.Text()))
    op.execute("UPDATE farmers SET private_note_owner_only = description, description = public_figure")
    op.drop_column('farmers', 'public_figure')

    op.alter_column('labour_group_wages', 'other_expenses', new_column_name='other_rate')

    _purchase_tables(True)


def downgrade() -> None:
    _purchase_tables(False)
    op.alter_column('labour_group_wages', 'other_rate', new_column_name='other_expenses')
    op.add_column('farmers', sa.Column('public_figure', sa.Text()))
    op.execute("UPDATE farmers SET public_figure = description, description = private_note_owner_only")
    op.drop_column('farmers', 'private_note_owner_only')
    op.alter_column('industries', 'industry_owner_mobile', new_column_name='owner_mobile')
    op.alter_column('industries', 'industry_owner_name', new_column_name='owner_name')
    op.alter_column('industries', 'industry_name_gu', new_column_name='industrialist_name_gu')
    op.alter_column('industries', 'industry_name', new_column_name='industrialist_name')
    op.drop_column('transporters', 'pet_name_gu')
