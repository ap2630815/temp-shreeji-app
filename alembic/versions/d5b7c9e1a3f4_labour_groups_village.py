"""labour_groups: village_id (a group is "group name - village name"); the name is unique per village

Revision ID: d5b7c9e1a3f4
Revises: c4a6b8d0f2e3
"""
import sqlalchemy as sa
from alembic import op

revision = 'd5b7c9e1a3f4'
down_revision = 'c4a6b8d0f2e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('labour_groups', sa.Column('village_id', sa.Integer(), sa.ForeignKey('villages.id'), nullable=True))
    op.create_index('ix_labour_groups_village_id', 'labour_groups', ['village_id'])
    op.drop_constraint('labour_groups_group_name_key', 'labour_groups', type_='unique')
    op.create_unique_constraint('uq_labour_groups_name_village', 'labour_groups', ['group_name', 'village_id'])
    # groups saved before villages were added (village_id empty) still need a unique name
    op.create_index('uq_labour_groups_name_no_village', 'labour_groups', ['group_name'], unique=True, postgresql_where=sa.text('village_id IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_labour_groups_name_no_village', table_name='labour_groups')
    op.drop_constraint('uq_labour_groups_name_village', 'labour_groups', type_='unique')
    op.create_unique_constraint('labour_groups_group_name_key', 'labour_groups', ['group_name'])
    op.drop_index('ix_labour_groups_village_id', table_name='labour_groups')
    op.drop_column('labour_groups', 'village_id')
