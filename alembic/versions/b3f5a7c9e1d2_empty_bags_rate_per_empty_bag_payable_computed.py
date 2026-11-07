"""empty_bags: rate_per_bag -> rate_per_empty_bag; payable_amount is calculated (no_of_empty_bags * rate_per_empty_bag), not stored

Revision ID: b3f5a7c9e1d2
Revises: a2e4f6b8c0d1
"""
import sqlalchemy as sa
from alembic import op

revision = 'b3f5a7c9e1d2'
down_revision = 'a2e4f6b8c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_empty_bags_amounts', 'empty_bags', type_='check')
    op.alter_column('empty_bags', 'rate_per_bag', new_column_name='rate_per_empty_bag')
    op.drop_column('empty_bags', 'payable_amount')
    op.create_check_constraint('ck_empty_bags_rate', 'empty_bags', 'rate_per_empty_bag >= 0')


def downgrade() -> None:
    op.drop_constraint('ck_empty_bags_rate', 'empty_bags', type_='check')
    op.add_column('empty_bags', sa.Column('payable_amount', sa.BigInteger(), nullable=False, server_default='0'))
    op.execute("UPDATE empty_bags SET payable_amount = rate_per_empty_bag * no_of_empty_bags")
    op.alter_column('empty_bags', 'rate_per_empty_bag', new_column_name='rate_per_bag')
    op.create_check_constraint('ck_empty_bags_amounts', 'empty_bags', 'rate_per_bag >= 0 AND payable_amount >= 0')
