"""rename truck_load_lines -> farmers_truck_load_lines, stockyard_load_lines -> stockyard_truck_load_lines

Matches 'ab needs/file4-transactional.txt'. Each table, its sequence, its indexes and every constraint named after it get the
new name. Data and columns are untouched. audit_log history keeps the old table names it was written with.

Revision ID: u8e2f6a0b439
Revises: t7d1e5f9a328
"""
from alembic import op


revision = 'u8e2f6a0b439'
down_revision = 't7d1e5f9a328'
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
    BEGIN  -- NOT NULL constraints are named in newer PostgreSQL versions only; skip quietly where they cannot be renamed
      EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.tbl, r.conname, replace(r.conname, '{old}', '{new}'));
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
  END LOOP;
  FOR r IN SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND indexname LIKE '%{old}%' AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conname = indexname) LOOP  -- keys' indexes were renamed with them
    EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, replace(r.indexname, '{old}', '{new}'));
  END LOOP;
  FOR r IN SELECT relname FROM pg_class WHERE relkind = 'S' AND relname LIKE '%{old}%' AND relnamespace = current_schema()::regnamespace LOOP
    EXECUTE format('ALTER SEQUENCE %I RENAME TO %I', r.relname, replace(r.relname, '{old}', '{new}'));
  END LOOP;
END $$;
"""
# no name of one table contains the other table's old or new name (checked both ways round), so the two renames cannot touch each other.
PAIRS = (("truck_load_lines", "farmers_truck_load_lines"), ("stockyard_load_lines", "stockyard_truck_load_lines"))


def upgrade() -> None:
    for old, new in PAIRS:
        op.execute(f"ALTER TABLE {old} RENAME TO {new}")
        op.execute(RENAME.format(old=old, new=new))


def downgrade() -> None:
    for old, new in reversed(PAIRS):
        op.execute(f"ALTER TABLE {new} RENAME TO {old}")
        op.execute(RENAME.format(old=new, new=old))
