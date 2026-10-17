"""rename purchase_farmer_entries -> purchase_farmers_entries (the name used in the spec)

The table, its sequence, its indexes and every constraint named after it (checks, the composite foreign key, the primary key and
the automatically named ones) get the new name, so the database matches the models and 'ab needs/file4'. Data is untouched;
columns keep their names (truck_load_lines.purchase_farmer_entry_id stays). audit_log history keeps the old table name it was
written with.

Revision ID: l9b3c7d1e540
Revises: k8a2b6c4d539
"""
from alembic import op


revision = 'l9b3c7d1e540'
down_revision = 'k8a2b6c4d539'
branch_labels = None
depends_on = None

RENAME = """
DO $$
DECLARE r record;
BEGIN
  -- constraints first (renaming the primary key also renames its index)
  FOR r IN SELECT c.conrelid::regclass::text AS tbl, c.conname FROM pg_constraint c
           WHERE c.conname LIKE '%{old}%' AND c.contype IN ('p', 'f', 'c', 'u') LOOP
    EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, replace(r.conname, '{old}', '{new}'));
  END LOOP;
  FOR r IN SELECT c.conrelid::regclass::text AS tbl, c.conname FROM pg_constraint c
           WHERE c.conname LIKE '%{old}%' AND c.contype = 'n' LOOP
    BEGIN  -- NOT NULL constraints are named in newer PostgreSQL versions only; skip quietly where they cannot be renamed
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


def upgrade() -> None:
    op.execute("ALTER TABLE purchase_farmer_entries RENAME TO purchase_farmers_entries")
    op.execute(RENAME.format(old="purchase_farmer_entries", new="purchase_farmers_entries"))


def downgrade() -> None:
    op.execute("ALTER TABLE purchase_farmers_entries RENAME TO purchase_farmer_entries")
    op.execute(RENAME.format(old="purchase_farmers_entries", new="purchase_farmer_entries"))
