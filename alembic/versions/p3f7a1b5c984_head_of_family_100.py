"""farmers.head_of_family: VARCHAR(60) -> VARCHAR(100)

The head of family is stored as 'Self' or surname + name + father's name (three words, separated by spaces); 100 characters leave room
for long names. Data is untouched.

Revision ID: p3f7a1b5c984
Revises: o2e6f0a4b873
"""
import sqlalchemy as sa
from alembic import op


revision = 'p3f7a1b5c984'
down_revision = 'o2e6f0a4b873'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('farmers', 'head_of_family', existing_type=sa.String(length=60), type_=sa.String(length=100), existing_nullable=True)


def downgrade() -> None:
    op.execute("UPDATE farmers SET head_of_family = left(head_of_family, 60)")
    op.alter_column('farmers', 'head_of_family', existing_type=sa.String(length=100), type_=sa.String(length=60), existing_nullable=True)
