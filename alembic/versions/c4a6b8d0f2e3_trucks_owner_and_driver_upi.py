"""trucks: upi_number -> truck_owner_upi_number, new driver_upi_number (both optional, 10 digits, "if different from mobile")

Revision ID: c4a6b8d0f2e3
Revises: b3f5a7c9e1d2
"""
import sqlalchemy as sa
from alembic import op

revision = 'c4a6b8d0f2e3'
down_revision = 'b3f5a7c9e1d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('trucks', 'upi_number', new_column_name='truck_owner_upi_number')
    op.execute("ALTER TABLE trucks RENAME CONSTRAINT ck_upi_number_10_digits TO ck_truck_owner_upi_number_10_digits")
    op.add_column('trucks', sa.Column('driver_upi_number', sa.String(length=10), nullable=True))
    op.create_check_constraint('ck_driver_upi_number_10_digits', 'trucks', "driver_upi_number IS NULL OR driver_upi_number ~ '^[0-9]{10}$'")


def downgrade() -> None:
    op.drop_constraint('ck_driver_upi_number_10_digits', 'trucks', type_='check')
    op.drop_column('trucks', 'driver_upi_number')
    op.execute("ALTER TABLE trucks RENAME CONSTRAINT ck_truck_owner_upi_number_10_digits TO ck_upi_number_10_digits")
    op.alter_column('trucks', 'truck_owner_upi_number', new_column_name='upi_number')
