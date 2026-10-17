"""direct_farmers_entries: a farmer entry made directly on the farmer ledger, on one form

One flat table holding the purchase_info columns (date, village, grain, rate, pay-after, terms) and the purchase_farmers_entries
columns (farmer, labour group, bags, amounts...) side by side, with a single description. A direct entry is paid through the
normal farmer payments; payment_allocations.payable_type gains the value 'direct_farmer' for allocations to these rows.

Additive: nothing is dropped.

Revision ID: k8a2b6c4d539
Revises: g4c8d2e9b075
"""
import sqlalchemy as sa
from alembic import op


revision = 'k8a2b6c4d539'
down_revision = 'g4c8d2e9b075'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('direct_farmers_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('direct_entry_date', sa.Date(), nullable=False),
    sa.Column('village_id', sa.Integer(), nullable=False),
    sa.Column('grain_id', sa.Integer(), nullable=False),
    sa.Column('grain_rate_per_20kg', sa.Integer(), nullable=False),
    sa.Column('pay_after_no_of_days', sa.Integer(), nullable=False),
    sa.Column('terms', sa.Text(), nullable=True),
    sa.Column('farmer_id', sa.Integer(), nullable=False),
    sa.Column('labour_group_id', sa.Integer(), nullable=False),
    sa.Column('no_of_filled_bags', sa.Integer(), nullable=False),
    sa.Column('extra_kilos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('no_of_handful_bags', sa.Integer(), server_default='0', nullable=False),
    sa.Column('total_available_bags', sa.Integer(), server_default='0', nullable=False),
    sa.Column('payable_amount', sa.BigInteger(), nullable=False),
    sa.Column('borrowed_amount', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('expected_raw_weight_per_bag', sa.Integer(), nullable=True),
    sa.Column('grain_quality_code', sa.Text(), nullable=True),
    sa.Column('grain_store_at', sa.Text(), nullable=True),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_direct_farmers_entries_business_year_format'),
    sa.CheckConstraint('borrowed_amount <= payable_amount', name='ck_direct_farmers_entries_borrowed_amount_le_payable_amount'),
    sa.CheckConstraint('borrowed_amount >= 0', name='ck_direct_farmers_entries_borrowed_amount'),
    sa.CheckConstraint('expected_raw_weight_per_bag IS NULL OR expected_raw_weight_per_bag >= 0', name='ck_direct_farmers_entries_expected_raw_weight_per_bag'),
    sa.CheckConstraint('extra_kilos >= 0', name='ck_direct_farmers_entries_extra_kilos'),
    sa.CheckConstraint('grain_rate_per_20kg > 0', name='ck_direct_farmers_entries_rate_positive'),
    sa.CheckConstraint('no_of_filled_bags >= 0', name='ck_direct_farmers_entries_no_of_filled_bags'),
    sa.CheckConstraint('no_of_handful_bags >= 0', name='ck_direct_farmers_entries_no_of_handful_bags'),
    sa.CheckConstraint('pay_after_no_of_days >= 0', name='ck_direct_farmers_entries_pay_after'),
    sa.CheckConstraint('payable_amount >= 0', name='ck_direct_farmers_entries_payable_amount'),
    sa.CheckConstraint('total_available_bags >= 0', name='ck_direct_farmers_entries_total_available_bags'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmers.id'], ),
    sa.ForeignKeyConstraint(['grain_id'], ['grains.id'], ),
    sa.ForeignKeyConstraint(['labour_group_id'], ['labour_groups.id'], ),
    sa.ForeignKeyConstraint(['village_id'], ['villages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_direct_farmers_entries_business_year', 'direct_farmers_entries', ['business_year'], unique=False)
    op.create_index('ix_direct_farmers_entries_farmer_id', 'direct_farmers_entries', ['farmer_id'], unique=False)
    op.create_index('ix_direct_farmers_entries_grain_id', 'direct_farmers_entries', ['grain_id'], unique=False)
    op.create_index('ix_direct_farmers_entries_village_id', 'direct_farmers_entries', ['village_id'], unique=False)
    op.drop_constraint('ck_alloc_payable_type', 'payment_allocations', type_='check')
    op.create_check_constraint('ck_alloc_payable_type', 'payment_allocations',
                               "payable_type IN ('farmer', 'direct_farmer', 'truck', 'labour_group', 'bag_supplier', 'broker')")


def downgrade() -> None:
    # payments already allocated to direct entries cannot stay once those entries are gone
    op.execute("DELETE FROM payment_allocations WHERE payable_type = 'direct_farmer'")
    op.drop_constraint('ck_alloc_payable_type', 'payment_allocations', type_='check')
    op.create_check_constraint('ck_alloc_payable_type', 'payment_allocations',
                               "payable_type IN ('farmer', 'truck', 'labour_group', 'bag_supplier', 'broker')")
    op.drop_table('direct_farmers_entries')
