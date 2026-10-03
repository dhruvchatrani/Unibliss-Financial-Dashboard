"""rename type to event_type

Revision ID: a123b456c78d
Revises: 9793b44f0aa7
Create Date: 2026-07-06 22:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a123b456c78d'
down_revision: Union[str, Sequence[str], None] = '9793b44f0aa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    with op.batch_alter_table('financial_events') as batch_op:
        batch_op.alter_column('type', new_column_name='event_type')
        batch_op.drop_column('refunds')

def downgrade() -> None:
    with op.batch_alter_table('financial_events') as batch_op:
        batch_op.alter_column('event_type', new_column_name='type')
        batch_op.add_column(sa.Column('refunds', sa.Float(), server_default='0.0'))
