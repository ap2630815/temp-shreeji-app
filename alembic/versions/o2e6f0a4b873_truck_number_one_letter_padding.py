"""a one-letter truck series is padded to two columns: GJ 14  X 6720 (GJ 01 DG 3345 is unchanged)

Existing 'GJ 14 X 6720' numbers get the extra space; the format check now expects it. The column stays VARCHAR(13), which both
forms fit exactly. Downgrade collapses the double space again.

Revision ID: o2e6f0a4b873
Revises: n1d5e9f3a762
"""
from alembic import op


revision = 'o2e6f0a4b873'
down_revision = 'n1d5e9f3a762'
branch_labels = None
depends_on = None

PADDED = "^[A-Z]{2} [0-9]{2} (?: [A-Z]|[A-Z]{2}) [0-9]{4}$"
SINGLE = "^[A-Z]{2} [0-9]{2} [A-Z]{1,2} [0-9]{4}$"


def upgrade() -> None:
    op.drop_constraint('ck_trucks_number_format', 'trucks', type_='check')
    op.execute(r"UPDATE trucks SET truck_number = regexp_replace(truck_number, '^([A-Z]{2} [0-9]{2}) ([A-Z]) ([0-9]{4})$', '\1  \2 \3')")
    op.create_check_constraint('ck_trucks_number_format', 'trucks', f"truck_number ~ '{PADDED}'")


def downgrade() -> None:
    op.drop_constraint('ck_trucks_number_format', 'trucks', type_='check')
    op.execute("UPDATE trucks SET truck_number = replace(truck_number, '  ', ' ')")
    op.create_check_constraint('ck_trucks_number_format', 'trucks', f"truck_number ~ '{SINGLE}'")
