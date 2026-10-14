"""spec schema (ab needs files 1, 2, 4, 5, 9): replace the business tables

Drops the old business tables (commencings, purchase_entries, old payments/receipts, ...) and creates the
tables described in file1-master1, file2-master2, file4-transactional and file5-payment-ledger, including
business_year on every dated record. users and audit_log are kept unchanged.

DESTRUCTIVE: all rows in the old business tables are deleted. downgrade() drops the new tables but cannot
bring the old ones back.

Revision ID: f3b7c9d2a614
Revises: e5a9c1d70b38
"""
import sqlalchemy as sa
from alembic import op


revision = 'f3b7c9d2a614'
down_revision = 'e5a9c1d70b38'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_allocations CASCADE")
    op.execute("DROP TABLE IF EXISTS payments CASCADE")
    op.execute("DROP TABLE IF EXISTS receipt_allocations CASCADE")
    op.execute("DROP TABLE IF EXISTS receipts CASCADE")
    op.execute("DROP TABLE IF EXISTS bilties CASCADE")
    op.execute("DROP TABLE IF EXISTS truck_load_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS truck_trips CASCADE")
    op.execute("DROP TABLE IF EXISTS labour_work CASCADE")
    op.execute("DROP TABLE IF EXISTS bag_supplies CASCADE")
    op.execute("DROP TABLE IF EXISTS purchase_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS commencings CASCADE")
    op.execute("DROP TABLE IF EXISTS farmers CASCADE")
    op.execute("DROP TABLE IF EXISTS bag_suppliers CASCADE")
    op.execute("DROP TABLE IF EXISTS labour_groups CASCADE")
    op.execute("DROP TABLE IF EXISTS transporters CASCADE")
    op.execute("DROP TABLE IF EXISTS trucks CASCADE")
    op.execute("DROP TABLE IF EXISTS industries CASCADE")
    op.execute("DROP TABLE IF EXISTS brokers CASCADE")
    op.execute("DROP TABLE IF EXISTS grains CASCADE")

    op.create_table('bag_suppliers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('name_gu', sa.String(length=120), nullable=True),
    sa.Column('pet_name', sa.String(length=30), nullable=False),
    sa.Column('mobile', sa.String(length=10), nullable=False),
    sa.Column('upi_number', sa.String(length=10), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mobile ~ '^[0-9]{10}$'", name='ck_mobile_10_digits'),
    sa.CheckConstraint("upi_number IS NULL OR upi_number ~ '^[0-9]{10}$'", name='ck_upi_number_10_digits'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mobile'),
    sa.UniqueConstraint('upi_number')
    )
    op.create_table('brokers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('broker_name', sa.String(length=120), nullable=False),
    sa.Column('broker_name_gu', sa.String(length=120), nullable=True),
    sa.Column('mobile', sa.String(length=10), nullable=False),
    sa.Column('upi_number', sa.String(length=10), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mobile ~ '^[0-9]{10}$'", name='ck_mobile_10_digits'),
    sa.CheckConstraint("upi_number IS NULL OR upi_number ~ '^[0-9]{10}$'", name='ck_upi_number_10_digits'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('broker_name'),
    sa.UniqueConstraint('mobile'),
    sa.UniqueConstraint('upi_number')
    )
    op.create_table('grains',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('grain_name', sa.String(length=30), nullable=False),
    sa.Column('grain_name_gu', sa.String(length=30), nullable=True),
    sa.Column('net_bag_weight', sa.Integer(), nullable=False),
    sa.Column('booking_weight', sa.Integer(), nullable=False),
    sa.Column('grain_terms', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('booking_weight IN (20, 100)', name='ck_grains_booking_weight'),
    sa.CheckConstraint('net_bag_weight IN (35, 50, 70, 100)', name='ck_grains_net_bag_weight'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('grain_name')
    )
    op.create_table('industries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('industrialist_name', sa.String(length=120), nullable=False),
    sa.Column('industrialist_name_gu', sa.String(length=120), nullable=True),
    sa.Column('owner_name', sa.String(length=120), nullable=False),
    sa.Column('owner_mobile', sa.String(length=10), nullable=False),
    sa.Column('supervisor_name', sa.String(length=120), nullable=False),
    sa.Column('supervisor_mobile', sa.String(length=10), nullable=False),
    sa.Column('grain', sa.String(length=60), nullable=False),
    sa.Column('location', sa.String(length=120), nullable=False),
    sa.Column('quality_expectation', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("owner_mobile ~ '^[0-9]{10}$'", name='ck_owner_mobile_10_digits'),
    sa.CheckConstraint("supervisor_mobile ~ '^[0-9]{10}$'", name='ck_supervisor_mobile_10_digits'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('industrialist_name')
    )
    op.create_table('labour_groups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_name', sa.String(length=30), nullable=False),
    sa.Column('group_name_gu', sa.String(length=30), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_name')
    )
    op.create_table('transporters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transporter_name', sa.String(length=120), nullable=False),
    sa.Column('pet_name', sa.String(length=30), nullable=False),
    sa.Column('location', sa.String(length=60), nullable=False),
    sa.Column('owner_name', sa.String(length=120), nullable=False),
    sa.Column('owner_name_gu', sa.String(length=120), nullable=True),
    sa.Column('mobile', sa.String(length=10), nullable=False),
    sa.Column('upi_number', sa.String(length=10), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mobile ~ '^[0-9]{10}$'", name='ck_mobile_10_digits'),
    sa.CheckConstraint("upi_number IS NULL OR upi_number ~ '^[0-9]{10}$'", name='ck_upi_number_10_digits'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mobile'),
    sa.UniqueConstraint('pet_name'),
    sa.UniqueConstraint('transporter_name'),
    sa.UniqueConstraint('upi_number')
    )
    op.create_table('trucks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('truck_number', sa.String(length=13), nullable=False),
    sa.Column('truck_owner_name', sa.String(length=120), nullable=False),
    sa.Column('truck_owner_mobile', sa.String(length=10), nullable=False),
    sa.Column('driver_name', sa.String(length=120), nullable=False),
    sa.Column('driver_mobile', sa.String(length=10), nullable=False),
    sa.Column('upi_number', sa.String(length=10), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("driver_mobile ~ '^[0-9]{10}$'", name='ck_driver_mobile_10_digits'),
    sa.CheckConstraint("truck_number ~ '^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$'", name='ck_trucks_number_format'),
    sa.CheckConstraint("truck_owner_mobile ~ '^[0-9]{10}$'", name='ck_truck_owner_mobile_10_digits'),
    sa.CheckConstraint("upi_number IS NULL OR upi_number ~ '^[0-9]{10}$'", name='ck_upi_number_10_digits'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('truck_number')
    )
    op.create_table('villages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('village_name', sa.String(length=30), nullable=False),
    sa.Column('village_name_gu', sa.String(length=30), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('village_name')
    )
    op.create_table('brokerages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('broker_id', sa.Integer(), nullable=False),
    sa.Column('grain_id', sa.Integer(), nullable=False),
    sa.Column('brokerage_per_bag', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('brokerage_per_bag >= 0', name='ck_brokerages_brokerage_nonneg'),
    sa.ForeignKeyConstraint(['broker_id'], ['brokers.id'], ),
    sa.ForeignKeyConstraint(['grain_id'], ['grains.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('broker_id', 'grain_id', name='uq_brokerages_broker_grain')
    )
    op.create_index('ix_brokerages_grain_id', 'brokerages', ['grain_id'], unique=False)
    op.create_table('farmers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('farmer_name', sa.String(length=120), nullable=False),
    sa.Column('farmer_name_gu', sa.String(length=120), nullable=True),
    sa.Column('head_of_family', sa.String(length=60), nullable=True),
    sa.Column('mobile', sa.String(length=10), nullable=False),
    sa.Column('email', sa.String(length=60), nullable=True),
    sa.Column('village_id', sa.Integer(), nullable=False),
    sa.Column('house', sa.Text(), nullable=True),
    sa.Column('upi_number', sa.String(length=10), nullable=True),
    sa.Column('bank_account_number', sa.String(length=30), nullable=True),
    sa.Column('bank_name', sa.String(length=30), nullable=True),
    sa.Column('bank_branch', sa.String(length=30), nullable=True),
    sa.Column('ifsc_code', sa.String(length=15), nullable=True),
    sa.Column('public_figure', sa.Text(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mobile ~ '^[0-9]{10}$'", name='ck_mobile_10_digits'),
    sa.CheckConstraint("upi_number IS NULL OR upi_number ~ '^[0-9]{10}$'", name='ck_upi_number_10_digits'),
    sa.ForeignKeyConstraint(['village_id'], ['villages.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bank_account_number'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('mobile'),
    sa.UniqueConstraint('upi_number')
    )
    op.create_index('ix_farmers_village_id', 'farmers', ['village_id'], unique=False)
    op.create_table('labour_group_wages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('labour_group_id', sa.Integer(), nullable=False),
    sa.Column('grain_id', sa.Integer(), nullable=False),
    sa.Column('weighing_rate', sa.Integer(), nullable=False),
    sa.Column('loading_rate', sa.Integer(), nullable=False),
    sa.Column('pulling_rate', sa.Integer(), nullable=False),
    sa.Column('mixing_rate', sa.Integer(), nullable=False),
    sa.Column('other_expenses', sa.Integer(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('weighing_rate >= 0 AND loading_rate >= 0 AND pulling_rate >= 0 AND mixing_rate >= 0', name='ck_labour_group_wages_rate_nonneg'),
    sa.ForeignKeyConstraint(['grain_id'], ['grains.id'], ),
    sa.ForeignKeyConstraint(['labour_group_id'], ['labour_groups.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('labour_group_id', 'grain_id', name='uq_labour_group_wages_group_grain')
    )
    op.create_index('ix_labour_group_wages_grain_id', 'labour_group_wages', ['grain_id'], unique=False)
    op.create_table('labour_work',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('labour_group_id', sa.Integer(), nullable=False),
    sa.Column('payable_amount', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('borrowing_amount', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('petrol', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('meal', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_labour_work_business_year_format'),
    sa.CheckConstraint('borrowing_amount <= payable_amount', name='ck_labour_work_borrowing_le_payable'),
    sa.CheckConstraint('payable_amount >= 0 AND borrowing_amount >= 0 AND petrol >= 0 AND meal >= 0', name='ck_labour_work_amount_nonneg'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['labour_group_id'], ['labour_groups.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_labour_work_business_year', 'labour_work', ['business_year'], unique=False)
    op.create_index('ix_labour_work_labour_group_id', 'labour_work', ['labour_group_id'], unique=False)
    op.create_table('labours',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('labour_name', sa.String(length=120), nullable=False),
    sa.Column('labour_name_gu', sa.String(length=120), nullable=True),
    sa.Column('labour_group_id', sa.Integer(), nullable=False),
    sa.Column('mobile', sa.String(length=10), nullable=False),
    sa.Column('upi_number', sa.String(length=10), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mobile ~ '^[0-9]{10}$'", name='ck_mobile_10_digits'),
    sa.CheckConstraint("upi_number IS NULL OR upi_number ~ '^[0-9]{10}$'", name='ck_upi_number_10_digits'),
    sa.ForeignKeyConstraint(['labour_group_id'], ['labour_groups.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mobile'),
    sa.UniqueConstraint('upi_number')
    )
    op.create_index('ix_labours_labour_group_id', 'labours', ['labour_group_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('party_type', sa.String(length=20), nullable=False),
    sa.Column('party_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('payment_date', sa.Date(), nullable=False),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('receiver_name', sa.String(length=120), nullable=False),
    sa.Column('receiver_mobile', sa.String(length=10), nullable=False),
    sa.Column('reference_no', sa.String(length=60), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_payments_business_year_format'),
    sa.CheckConstraint("method IN ('cash', 'cheque', 'upi', 'bank')", name='ck_payments_method'),
    sa.CheckConstraint("party_type IN ('farmer', 'truck', 'labour_group', 'bag_supplier', 'broker')", name='ck_payments_party_type'),
    sa.CheckConstraint("receiver_mobile ~ '^[0-9]{10}$'", name='ck_payments_receiver_mobile'),
    sa.CheckConstraint("status IN ('partial', 'final', 'complete')", name='ck_payments_status'),
    sa.CheckConstraint('amount > 0', name='ck_payments_amount_positive'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_payments_business_year', 'payments', ['business_year'], unique=False)
    op.create_index('ix_payments_party', 'payments', ['party_type', 'party_id'], unique=False)
    op.create_table('purchase_info',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('purchase_info_date', sa.Date(), nullable=False),
    sa.Column('village_id', sa.Integer(), nullable=False),
    sa.Column('grain_id', sa.Integer(), nullable=False),
    sa.Column('grain_rate_per_20kg', sa.Integer(), nullable=False),
    sa.Column('pay_after_no_of_days', sa.Integer(), nullable=False),
    sa.Column('purchase_info_terms', sa.Text(), nullable=True),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_purchase_info_business_year_format'),
    sa.CheckConstraint('grain_rate_per_20kg > 0', name='ck_purchase_info_rate_positive'),
    sa.CheckConstraint('pay_after_no_of_days >= 0', name='ck_purchase_info_pay_after'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['grain_id'], ['grains.id'], ),
    sa.ForeignKeyConstraint(['village_id'], ['villages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_purchase_info_business_year', 'purchase_info', ['business_year'], unique=False)
    op.create_index('ix_purchase_info_grain_id', 'purchase_info', ['grain_id'], unique=False)
    op.create_index('ix_purchase_info_village_id', 'purchase_info', ['village_id'], unique=False)
    op.create_table('receipts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('industry_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('receipt_date', sa.Date(), nullable=False),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('reference_no', sa.String(length=60), nullable=True),
    sa.Column('payer_name', sa.String(length=120), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_receipts_business_year_format'),
    sa.CheckConstraint("method IN ('cash', 'cheque', 'upi', 'bank')", name='ck_receipts_method'),
    sa.CheckConstraint('amount > 0', name='ck_receipts_amount'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['industry_id'], ['industries.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_receipts_business_year', 'receipts', ['business_year'], unique=False)
    op.create_index('ix_receipts_industry_id', 'receipts', ['industry_id'], unique=False)
    op.create_table('bag_supplies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('supplier_id', sa.Integer(), nullable=False),
    sa.Column('farmer_id', sa.Integer(), nullable=False),
    sa.Column('supply_date', sa.Date(), nullable=False),
    sa.Column('payable_amount', sa.BigInteger(), nullable=False),
    sa.Column('rate_per_bag', sa.Integer(), nullable=False),
    sa.Column('no_of_bags', sa.Integer(), nullable=False),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_bag_supplies_business_year_format'),
    sa.CheckConstraint('rate_per_bag > 0 AND no_of_bags > 0', name='ck_bag_supplies_positive'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmers.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['bag_suppliers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bag_supplies_business_year', 'bag_supplies', ['business_year'], unique=False)
    op.create_index('ix_bag_supplies_farmer_id', 'bag_supplies', ['farmer_id'], unique=False)
    op.create_index('ix_bag_supplies_supplier_id', 'bag_supplies', ['supplier_id'], unique=False)
    op.create_table('broker_bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('booking_date', sa.Date(), nullable=False),
    sa.Column('brokerage_id', sa.Integer(), nullable=False),
    sa.Column('industry_id', sa.Integer(), nullable=False),
    sa.Column('grain_rate_per_booking_weight', sa.Integer(), nullable=False),
    sa.Column('truck_size', sa.Integer(), nullable=False),
    sa.Column('percentage_deduction', sa.Float(), nullable=True),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_broker_bookings_business_year_format'),
    sa.CheckConstraint('percentage_deduction IS NULL OR percentage_deduction BETWEEN 0 AND 5', name='ck_broker_bookings_percentage_deduction'),
    sa.CheckConstraint('truck_size IN (10, 15, 20, 25, 30, 35)', name='ck_broker_bookings_truck_size'),
    sa.ForeignKeyConstraint(['brokerage_id'], ['brokerages.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['industry_id'], ['industries.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_broker_bookings_brokerage_id', 'broker_bookings', ['brokerage_id'], unique=False)
    op.create_index('ix_broker_bookings_business_year', 'broker_bookings', ['business_year'], unique=False)
    op.create_index('ix_broker_bookings_industry_id', 'broker_bookings', ['industry_id'], unique=False)
    op.create_table('payment_allocations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('payment_id', sa.Integer(), nullable=False),
    sa.Column('payable_type', sa.String(length=15), server_default='farmer', nullable=False),
    sa.Column('payable_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.CheckConstraint("payable_type IN ('farmer', 'truck', 'labour_group', 'bag_supplier', 'broker')", name='ck_alloc_payable_type'),
    sa.CheckConstraint('amount > 0', name='ck_alloc_amount_positive'),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_alloc_payable', 'payment_allocations', ['payable_type', 'payable_id'], unique=False)
    op.create_table('purchase_farmer_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('purchase_entry_date', sa.Date(), nullable=False),
    sa.Column('purchase_info_id', sa.Integer(), nullable=False),
    sa.Column('farmer_id', sa.Integer(), nullable=False),
    sa.Column('labour_group_id', sa.Integer(), nullable=False),
    sa.Column('no_of_filled_bags', sa.Integer(), nullable=False),
    sa.Column('extra_kilos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('payable_amount', sa.BigInteger(), nullable=False),
    sa.Column('borrowed_amount', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('expected_raw_weight_per_bag', sa.Integer(), nullable=True),
    sa.Column('grain_quality_code', sa.Text(), nullable=True),
    sa.Column('grain_store_at', sa.Text(), nullable=True),
    sa.Column('no_of_handful_bags', sa.Integer(), server_default='0', nullable=False),
    sa.Column('total_available_bags', sa.Integer(), server_default='0', nullable=False),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_purchase_farmer_entries_business_year_format'),
    sa.CheckConstraint('borrowed_amount <= payable_amount', name='ck_purchase_farmer_entries_borrowed_amount_le_payable_amount'),
    sa.CheckConstraint('borrowed_amount >= 0', name='ck_purchase_farmer_entries_borrowed_amount'),
    sa.CheckConstraint('expected_raw_weight_per_bag IS NULL OR expected_raw_weight_per_bag >= 0', name='ck_purchase_farmer_entries_expected_raw_weight_per_bag'),
    sa.CheckConstraint('extra_kilos >= 0', name='ck_purchase_farmer_entries_extra_kilos'),
    sa.CheckConstraint('no_of_filled_bags >= 0', name='ck_purchase_farmer_entries_no_of_filled_bags'),
    sa.CheckConstraint('no_of_handful_bags >= 0', name='ck_purchase_farmer_entries_no_of_handful_bags'),
    sa.CheckConstraint('payable_amount >= 0', name='ck_purchase_farmer_entries_payable_amount'),
    sa.CheckConstraint('total_available_bags >= 0', name='ck_purchase_farmer_entries_total_available_bags'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmers.id'], ),
    sa.ForeignKeyConstraint(['labour_group_id'], ['labour_groups.id'], ),
    sa.ForeignKeyConstraint(['purchase_info_id'], ['purchase_info.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_purchase_farmer_entries_business_year', 'purchase_farmer_entries', ['business_year'], unique=False)
    op.create_index('ix_purchase_farmer_entries_farmer_id', 'purchase_farmer_entries', ['farmer_id'], unique=False)
    op.create_index('ix_purchase_farmer_entries_labour_group_id', 'purchase_farmer_entries', ['labour_group_id'], unique=False)
    op.create_index('ix_purchase_farmer_entries_purchase_info_id', 'purchase_farmer_entries', ['purchase_info_id'], unique=False)
    op.create_table('truck_trips',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trip_date', sa.Date(), nullable=False),
    sa.Column('broker_booking_id', sa.Integer(), nullable=False),
    sa.Column('truck_id', sa.Integer(), nullable=False),
    sa.Column('transporter_id', sa.Integer(), nullable=False),
    sa.Column('labour_group_id', sa.Integer(), nullable=False),
    sa.Column('rent_per_ton', sa.Integer(), server_default='0', nullable=False),
    sa.Column('rent_per_bag', sa.Integer(), server_default='0', nullable=False),
    sa.Column('advance_amount', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('other_payable', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('other_deduction', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_truck_trips_business_year_format'),
    sa.CheckConstraint('(rent_per_ton > 0 AND rent_per_bag = 0) OR (rent_per_ton = 0 AND rent_per_bag > 0)', name='ck_truck_trips_rent_nonneg'),
    sa.CheckConstraint('advance_amount >= 0 AND other_payable >= 0 AND other_deduction >= 0', name='ck_truck_trips_amount_nonneg'),
    sa.ForeignKeyConstraint(['broker_booking_id'], ['broker_bookings.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['labour_group_id'], ['labour_groups.id'], ),
    sa.ForeignKeyConstraint(['transporter_id'], ['transporters.id'], ),
    sa.ForeignKeyConstraint(['truck_id'], ['trucks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_truck_trips_broker_booking_id', 'truck_trips', ['broker_booking_id'], unique=False)
    op.create_index('ix_truck_trips_business_year', 'truck_trips', ['business_year'], unique=False)
    op.create_table('bilties',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bilty_date', sa.Date(), nullable=False),
    sa.Column('bill_number', sa.Integer(), nullable=False),
    sa.Column('truck_trip_id', sa.Integer(), nullable=False),
    sa.Column('total_bags_in_truck', sa.Integer(), nullable=False),
    sa.Column('any_rate_change', sa.Integer(), server_default='0', nullable=False),
    sa.Column('merchant_total_weight', sa.Integer(), nullable=False),
    sa.Column('merchant_tare_weight', sa.Integer(), nullable=False),
    sa.Column('industry_total_weight', sa.Integer(), nullable=True),
    sa.Column('industry_tare_weight', sa.Integer(), nullable=True),
    sa.Column('business_year', sa.String(length=7), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("business_year ~ '^[0-9]{4}-[0-9]{2}$'", name='ck_bilties_business_year_format'),
    sa.CheckConstraint('(industry_total_weight IS NULL AND industry_tare_weight IS NULL) OR (industry_total_weight > industry_tare_weight AND industry_tare_weight >= 0)', name='ck_bilties_industry_weights'),
    sa.CheckConstraint('bill_number > 0', name='ck_bilties_bill_number'),
    sa.CheckConstraint('merchant_total_weight > merchant_tare_weight AND merchant_tare_weight >= 0', name='ck_bilties_merchant_weights'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['truck_trip_id'], ['truck_trips.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_year', 'bill_number', name='uq_bilties_year_bill'),
    sa.UniqueConstraint('truck_trip_id')
    )
    op.create_index('ix_bilties_business_year', 'bilties', ['business_year'], unique=False)
    op.create_table('truck_load_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('purchase_farmer_entry_id', sa.Integer(), nullable=False),
    sa.Column('no_of_loaded_bags', sa.Integer(), nullable=False),
    sa.Column('total_remaining_bags', sa.Integer(), nullable=False),
    sa.CheckConstraint('no_of_loaded_bags > 0', name='ck_truck_load_lines_no_of_loaded_bags'),
    sa.CheckConstraint('total_remaining_bags >= 0', name='ck_truck_load_lines_total_remaining_bags'),
    sa.ForeignKeyConstraint(['purchase_farmer_entry_id'], ['purchase_farmer_entries.id'], ),
    sa.ForeignKeyConstraint(['trip_id'], ['truck_trips.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trip_id', 'purchase_farmer_entry_id', name='uq_truck_load_lines_trip_entry')
    )
    op.create_index('ix_truck_load_lines_purchase_farmer_entry_id', 'truck_load_lines', ['purchase_farmer_entry_id'], unique=False)
    op.create_table('receipt_allocations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('receipt_id', sa.Integer(), nullable=False),
    sa.Column('bilty_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('amount > 0', name='ck_receipt_alloc_amount'),
    sa.ForeignKeyConstraint(['bilty_id'], ['bilties.id'], ),
    sa.ForeignKeyConstraint(['receipt_id'], ['receipts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_receipt_alloc_bilty', 'receipt_allocations', ['bilty_id'], unique=False)


def downgrade() -> None:
    op.drop_table('receipt_allocations')
    op.drop_table('truck_load_lines')
    op.drop_table('bilties')
    op.drop_table('truck_trips')
    op.drop_table('purchase_farmer_entries')
    op.drop_table('payment_allocations')
    op.drop_table('broker_bookings')
    op.drop_table('bag_supplies')
    op.drop_table('receipts')
    op.drop_table('purchase_info')
    op.drop_table('payments')
    op.drop_table('labours')
    op.drop_table('labour_work')
    op.drop_table('labour_group_wages')
    op.drop_table('farmers')
    op.drop_table('brokerages')
    op.drop_table('villages')
    op.drop_table('trucks')
    op.drop_table('transporters')
    op.drop_table('labour_groups')
    op.drop_table('industries')
    op.drop_table('grains')
    op.drop_table('brokers')
    op.drop_table('bag_suppliers')
