"""truck numbers are stored in the standard spaced format: GJ 01 DG 3345, GJ 14 X 6720

Existing GJ03AB1234-style numbers get their spaces; the format check now expects them. VARCHAR(13) already fits the longest
form (GJ 01 DG 3345). Downgrade removes the spaces again.

Revision ID: n1d5e9f3a762
Revises: m0c4d8e2f651
"""
from alembic import op


revision = 'n1d5e9f3a762'
down_revision = 'm0c4d8e2f651'
branch_labels = None
depends_on = None

SPACED = "^[A-Z]{2} [0-9]{2} [A-Z]{1,2} [0-9]{4}$"
PLAIN = "^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$"


def upgrade() -> None:
    op.drop_constraint('ck_trucks_number_format', 'trucks', type_='check')
    op.execute(r"UPDATE trucks SET truck_number = regexp_replace(truck_number, '^([A-Z]{2})([0-9]{2})([A-Z]{1,2})([0-9]{4})$', '\1 \2 \3 \4')")
    op.create_check_constraint('ck_trucks_number_format', 'trucks', f"truck_number ~ '{SPACED}'")


def downgrade() -> None:
    op.drop_constraint('ck_trucks_number_format', 'trucks', type_='check')
    op.execute("UPDATE trucks SET truck_number = replace(truck_number, ' ', '')")
    op.create_check_constraint('ck_trucks_number_format', 'trucks', f"truck_number ~ '{PLAIN}'")
