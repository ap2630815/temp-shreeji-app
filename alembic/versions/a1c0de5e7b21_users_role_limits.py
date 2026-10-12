"""users role limits: max 1 owner, max 2 accountants

Revision ID: a1c0de5e7b21
Revises: 843f48f3161e
"""
from alembic import op


revision = 'a1c0de5e7b21'
down_revision = '843f48f3161e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('uq_users_single_owner', 'users', ['role'], unique=True,
                    postgresql_where="role = 'owner'")
    op.execute("""
    CREATE FUNCTION check_max_accountants() RETURNS trigger AS $$
    BEGIN
        IF NEW.role = 'accountant' AND (
            SELECT count(*) FROM users
            WHERE role = 'accountant' AND id IS DISTINCT FROM NEW.id
        ) >= 2 THEN
            RAISE EXCEPTION 'At most 2 accountant users are allowed'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_users_max_accountants
    BEFORE INSERT OR UPDATE OF role ON users
    FOR EACH ROW EXECUTE FUNCTION check_max_accountants()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_users_max_accountants ON users")
    op.execute("DROP FUNCTION check_max_accountants()")
    op.drop_index('uq_users_single_owner', table_name='users')
