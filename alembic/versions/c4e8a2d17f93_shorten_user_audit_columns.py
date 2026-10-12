"""shorten users / audit_log text columns to match file-database.txt

Revision ID: c4e8a2d17f93
Revises: b7d3f0a91c42
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e8a2d17f93'
down_revision = 'b7d3f0a91c42'
branch_labels = None
depends_on = None

# (table, column, new length, old length)
CHANGES = [
    ('users', 'username', 30, 50),
    ('users', 'role', 15, 20),
    ('audit_log', 'username', 30, 50),
    ('audit_log', 'action', 15, 20),
    ('audit_log', 'table_name', 30, 50),
]


def _drop_role_dependents() -> None:
    # Postgres cannot retype a column that a trigger or partial-index predicate refers to
    op.execute("DROP TRIGGER trg_users_max_accountants ON users")
    op.drop_index('uq_users_single_owner', table_name='users')


def _create_role_dependents() -> None:
    op.create_index('uq_users_single_owner', 'users', ['role'], unique=True, postgresql_where="role = 'owner'")
    op.execute("""
    CREATE TRIGGER trg_users_max_accountants
    BEFORE INSERT OR UPDATE OF role ON users
    FOR EACH ROW EXECUTE FUNCTION check_max_accountants()
    """)


def upgrade() -> None:
    _drop_role_dependents()
    for table, column, new, old in CHANGES:
        op.alter_column(table, column, type_=sa.String(length=new), existing_type=sa.String(length=old), existing_nullable=False)
    _create_role_dependents()


def downgrade() -> None:
    _drop_role_dependents()
    for table, column, new, old in CHANGES:
        op.alter_column(table, column, type_=sa.String(length=old), existing_type=sa.String(length=new), existing_nullable=False)
    _create_role_dependents()
