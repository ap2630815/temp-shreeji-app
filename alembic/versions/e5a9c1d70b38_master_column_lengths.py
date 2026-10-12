"""master tables: varchar lengths as in file-master.txt

Revision ID: e5a9c1d70b38
Revises: d2f6b8c35a10
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5a9c1d70b38'
down_revision = 'd2f6b8c35a10'
branch_labels = None
depends_on = None

# table -> [(column, new length, old length, nullable)]
CHANGES = {
    'farmers': [
        ('name', 120, 128, False), ('name_gu', 120, 128, True), ('head_of_family', 60, 64, True),
        ('email', 60, 64, True), ('village', 30, 32, False), ('village_gu', 30, 32, True),
        ('bank_account_number', 30, 32, True), ('bank_name', 30, 32, True), ('bank_branch', 30, 32, True),
        ('ifsc_code', 15, 16, True),
    ],
    'bag_suppliers': [
        ('name', 120, 200, False), ('name_gu', 120, 200, True), ('pet_name', 30, 100, False), ('email', 60, 254, True),
    ],
    'labour_groups': [
        ('name', 120, 200, False), ('name_gu', 120, 200, True), ('group_name', 30, 100, False), ('group_name_gu', 30, 100, True),
    ],
    'transporters': [
        ('name', 120, 200, False), ('pet_name', 30, 100, False), ('location', 60, 100, False),
        ('owner_name', 120, 200, False), ('owner_name_gu', 120, 200, True),
    ],
    'trucks': [
        ('truck_number', 13, 10, False), ('owner_name', 120, 200, False), ('driver_name', 120, 200, False),
    ],
    'industries': [
        ('name', 120, 200, False), ('name_gu', 120, 200, True), ('owner_name', 120, 200, False),
        ('supervisor_name', 120, 200, False), ('product', 60, 100, False), ('location', 120, 100, False),
    ],
    'brokers': [('name', 120, 200, False), ('name_gu', 120, 200, True)],
    'grains': [('name', 30, 100, False), ('name_gu', 30, 100, True)],
}


def upgrade() -> None:
    for table, cols in CHANGES.items():
        for column, new, old, nullable in cols:
            op.alter_column(table, column, type_=sa.String(length=new), existing_type=sa.String(length=old), existing_nullable=nullable)


def downgrade() -> None:
    for table, cols in CHANGES.items():
        for column, new, old, nullable in cols:
            op.alter_column(table, column, type_=sa.String(length=old), existing_type=sa.String(length=new), existing_nullable=nullable)
