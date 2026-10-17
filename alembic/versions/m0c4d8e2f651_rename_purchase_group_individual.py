"""rename purchase_info -> purchase_group, purchase_info_farmers -> purchase_group_farmers, direct_farmers_entries -> purchase_individuals

Tables, sequences, indexes, constraints, the purchase_info_* columns (purchase_info_id/date/terms), direct_entry_date and the
payment_allocations.payable_type value 'direct_farmer' (now 'purchase_individual') get the new names. Data is untouched.
audit_log history keeps the old table names it was written with.

Revision ID: m0c4d8e2f651
Revises: l9b3c7d1e540
"""
from alembic import op


revision = 'm0c4d8e2f651'
down_revision = 'l9b3c7d1e540'
branch_labels = None
depends_on = None

RENAME = """
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.conrelid::regclass::text AS tbl, c.conname FROM pg_constraint c
           WHERE c.conname LIKE '%{old}%' AND c.contype IN ('p', 'f', 'c', 'u') LOOP
    EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, replace(r.conname, '{old}', '{new}'));
  END LOOP;
  FOR r IN SELECT c.conrelid::regclass::text AS tbl, c.conname FROM pg_constraint c
           WHERE c.conname LIKE '%{old}%' AND c.contype = 'n' LOOP
    BEGIN
      EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, replace(r.conname, '{old}', '{new}'));
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
  END LOOP;
  FOR r IN SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND indexname LIKE '%{old}%' LOOP
    EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, replace(r.indexname, '{old}', '{new}'));
  END LOOP;
  FOR r IN SELECT relname FROM pg_class WHERE relkind = 'S' AND relname LIKE '%{old}%' AND relnamespace = current_schema()::regnamespace LOOP
    EXECUTE format('ALTER SEQUENCE %I RENAME TO %I', r.relname, replace(r.relname, '{old}', '{new}'));
  END LOOP;
END $$;
"""

COLUMNS = [("purchase_group_farmers", "purchase_info_id", "purchase_group_id"),
           ("purchase_farmers_entries", "purchase_info_id", "purchase_group_id"),
           ("purchase_group", "purchase_info_date", "purchase_group_date"),
           ("purchase_group", "purchase_info_terms", "purchase_group_terms"),
           ("purchase_individuals", "direct_entry_date", "purchase_individual_date")]

# (old, new) in the order they are applied; the longer purchase_info_farmers goes first
NAMES = [("purchase_info_farmers", "purchase_group_farmers"), ("purchase_info", "purchase_group"),
         ("direct_farmers_entries", "purchase_individuals")]


def _alloc_check(kind: str) -> str:
    return f"payable_type IN ('farmer', '{kind}', 'truck', 'labour_group', 'bag_supplier', 'broker')"


def upgrade() -> None:
    for old, new in NAMES:
        op.execute(f"ALTER TABLE {old} RENAME TO {new}")
    for table, old, new in COLUMNS:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    for old, new in NAMES:
        op.execute(RENAME.format(old=old, new=new))
    op.drop_constraint('ck_alloc_payable_type', 'payment_allocations', type_='check')
    op.execute("ALTER TABLE payment_allocations ALTER COLUMN payable_type TYPE VARCHAR(25)")  # 'purchase_individual' is 19 characters
    op.execute("UPDATE payment_allocations SET payable_type = 'purchase_individual' WHERE payable_type = 'direct_farmer'")
    op.create_check_constraint('ck_alloc_payable_type', 'payment_allocations', _alloc_check('purchase_individual'))


def downgrade() -> None:
    op.drop_constraint('ck_alloc_payable_type', 'payment_allocations', type_='check')
    op.execute("UPDATE payment_allocations SET payable_type = 'direct_farmer' WHERE payable_type = 'purchase_individual'")
    op.create_check_constraint('ck_alloc_payable_type', 'payment_allocations', _alloc_check('direct_farmer'))
    op.execute("ALTER TABLE payment_allocations ALTER COLUMN payable_type TYPE VARCHAR(15)")
    for old, new in reversed(NAMES):
        op.execute(RENAME.format(old=new, new=old))
    for table, old, new in COLUMNS:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN {new} TO {old}")
    for old, new in reversed(NAMES):
        op.execute(f"ALTER TABLE {new} RENAME TO {old}")
