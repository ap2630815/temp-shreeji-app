"""empty_bags: industry_id (bought from an industry instead of a seller), rate_per_bag, payable_amount;
payments / allocations accept the 'industry' party type and the 'empty_bag' payable type

Revision ID: a2e4f6b8c0d1
Revises: f1d3e7a1b5c0
"""
import sqlalchemy as sa
from alembic import op

revision = 'a2e4f6b8c0d1'
down_revision = 'f1d3e7a1b5c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('empty_bags', sa.Column('industry_id', sa.Integer(), sa.ForeignKey('industries.id')))
    op.add_column('empty_bags', sa.Column('rate_per_bag', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('empty_bags', sa.Column('payable_amount', sa.BigInteger(), nullable=False, server_default='0'))
    op.create_index('ix_empty_bags_industry_id', 'empty_bags', ['industry_id'])
    op.create_check_constraint('ck_empty_bags_amounts', 'empty_bags', 'rate_per_bag >= 0 AND payable_amount >= 0')
    op.create_check_constraint('ck_empty_bags_one_seller_or_industry', 'empty_bags', 'empty_bag_seller_id IS NULL OR industry_id IS NULL')
    op.drop_constraint('ck_payments_party_type', 'payments', type_='check')
    op.create_check_constraint('ck_payments_party_type', 'payments', "party_type IN ('farmer', 'truck', 'labour_group', 'empty_bag_seller', 'industry', 'broker')")
    op.drop_constraint('ck_alloc_payable_type', 'payment_allocations', type_='check')
    op.create_check_constraint('ck_alloc_payable_type', 'payment_allocations',
                               "payable_type IN ('farmer', 'purchase_individual', 'truck', 'labour_group', 'empty_bag_seller', 'empty_bag', 'broker')")


def downgrade() -> None:
    op.execute("DELETE FROM payment_allocations WHERE payable_type = 'empty_bag'")
    op.execute("DELETE FROM payments WHERE party_type = 'industry'")
    op.drop_constraint('ck_alloc_payable_type', 'payment_allocations', type_='check')
    op.create_check_constraint('ck_alloc_payable_type', 'payment_allocations',
                               "payable_type IN ('farmer', 'purchase_individual', 'truck', 'labour_group', 'empty_bag_seller', 'broker')")
    op.drop_constraint('ck_payments_party_type', 'payments', type_='check')
    op.create_check_constraint('ck_payments_party_type', 'payments', "party_type IN ('farmer', 'truck', 'labour_group', 'empty_bag_seller', 'broker')")
    op.drop_constraint('ck_empty_bags_one_seller_or_industry', 'empty_bags', type_='check')
    op.drop_constraint('ck_empty_bags_amounts', 'empty_bags', type_='check')
    op.drop_index('ix_empty_bags_industry_id', table_name='empty_bags')
    for col in ('payable_amount', 'rate_per_bag', 'industry_id'):
        op.drop_column('empty_bags', col)
