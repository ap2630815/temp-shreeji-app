"""expected_raw_weight_per_bag on purchase_farmers_entries and purchase_individuals: FLOAT NOT NULL (>= 0)

As in 'ab needs/file4-transactional.txt': every purchase carries an expected raw weight per bag that starts at the grain's value and
is editable. Rows without one take their grain's value.

Revision ID: w1a4b8c2d651
Revises: v9f3a7b1c540
"""
import sqlalchemy as sa
from alembic import op


revision = 'w1a4b8c2d651'
down_revision = 'v9f3a7b1c540'
branch_labels = None
depends_on = None

TABLES = (
    ('purchase_farmers_entries', 'ck_purchase_farmers_entries_expected_raw_weight_per_bag',
     "UPDATE purchase_farmers_entries e SET expected_raw_weight_per_bag = g.expected_raw_weight_per_bag "
     "FROM purchase_group p JOIN grains g ON g.id = p.grain_id WHERE p.id = e.purchase_group_id AND e.expected_raw_weight_per_bag IS NULL"),
    ('purchase_individuals', 'ck_purchase_individuals_expected_raw_weight_per_bag',
     "UPDATE purchase_individuals e SET expected_raw_weight_per_bag = g.expected_raw_weight_per_bag "
     "FROM grains g WHERE g.id = e.grain_id AND e.expected_raw_weight_per_bag IS NULL"),
)


def upgrade() -> None:
    for table, check, backfill in TABLES:
        op.drop_constraint(check, table, type_='check')
        op.execute(backfill)
        op.alter_column(table, 'expected_raw_weight_per_bag', existing_type=sa.Integer(), type_=sa.Float(), nullable=False,
                        postgresql_using='expected_raw_weight_per_bag::double precision')
        op.create_check_constraint(check, table, 'expected_raw_weight_per_bag >= 0')


def downgrade() -> None:
    for table, check, _ in TABLES:
        op.drop_constraint(check, table, type_='check')
        op.alter_column(table, 'expected_raw_weight_per_bag', existing_type=sa.Float(), type_=sa.Integer(), nullable=True,
                        postgresql_using='round(expected_raw_weight_per_bag)::integer')
        op.create_check_constraint(check, table, 'expected_raw_weight_per_bag IS NULL OR expected_raw_weight_per_bag >= 0')
