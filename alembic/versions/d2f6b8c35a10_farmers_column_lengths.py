"""farmers: column lengths as in file-master.txt

Revision ID: d2f6b8c35a10
Revises: c4e8a2d17f93
"""
from alembic import op
import sqlalchemy as sa


revision = 'd2f6b8c35a10'
down_revision = 'c4e8a2d17f93'
branch_labels = None
depends_on = None

# (column, new length, old length, nullable)
CHANGES = [
    ('name', 128, 200, False),
    ('name_gu', 128, 200, True),
    ('head_of_family', 64, 200, True),
    ('email', 64, 254, True),
    ('village', 32, 100, False),
    ('village_gu', 32, 100, True),
    ('bank_account_number', 32, 30, True),
    ('bank_name', 32, 100, True),
    ('bank_branch', 32, 100, True),
    ('ifsc_code', 16, 11, True),
]


def upgrade() -> None:
    for column, new, old, nullable in CHANGES:
        op.alter_column('farmers', column, type_=sa.String(length=new), existing_type=sa.String(length=old), existing_nullable=nullable)


def downgrade() -> None:
    for column, new, old, nullable in CHANGES:
        op.alter_column('farmers', column, type_=sa.String(length=old), existing_type=sa.String(length=new), existing_nullable=nullable)
