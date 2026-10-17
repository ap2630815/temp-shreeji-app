"""purchase_info_farmers: the farmers who took part in each purchase_info (deal)

A purchase_info is one deal between the owner and a few farmers of a village; a village has many. The listed farmers
are picked when the deal is made; purchase_farmer_entries (the farmer ledger) can only be made for a listed farmer.

Additive: existing entries' (purchase_info, farmer) pairs are copied into the new list before the foreign key is added,
so no data is lost.

Revision ID: g4c8d2e9b075
Revises: f3b7c9d2a614
"""
import sqlalchemy as sa
from alembic import op


revision = 'g4c8d2e9b075'
down_revision = 'f3b7c9d2a614'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('purchase_info_farmers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('purchase_info_id', sa.Integer(), nullable=False),
    sa.Column('farmer_id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['farmer_id'], ['farmers.id'], ),
    sa.ForeignKeyConstraint(['purchase_info_id'], ['purchase_info.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('purchase_info_id', 'farmer_id', name='uq_purchase_info_farmers_info_farmer')
    )
    op.create_index('ix_purchase_info_farmers_farmer_id', 'purchase_info_farmers', ['farmer_id'], unique=False)
    op.execute("""
    INSERT INTO purchase_info_farmers (purchase_info_id, farmer_id)
    SELECT DISTINCT purchase_info_id, farmer_id FROM purchase_farmer_entries
    """)
    op.create_foreign_key('fk_purchase_farmer_entries_listed_farmer', 'purchase_farmer_entries', 'purchase_info_farmers',
                          ['purchase_info_id', 'farmer_id'], ['purchase_info_id', 'farmer_id'])


def downgrade() -> None:
    op.drop_constraint('fk_purchase_farmer_entries_listed_farmer', 'purchase_farmer_entries', type_='foreignkey')
    op.drop_index('ix_purchase_info_farmers_farmer_id', table_name='purchase_info_farmers')
    op.drop_table('purchase_info_farmers')
