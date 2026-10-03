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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c['name'] for c in inspector.get_columns('financial_events')]
    
    if 'type' in columns or 'refunds' in columns:
        with op.batch_alter_table('financial_events') as batch_op:
            if 'type' in columns:
                batch_op.alter_column('type', new_column_name='event_type')
            if 'refunds' in columns:
                batch_op.drop_column('refunds')

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c['name'] for c in inspector.get_columns('financial_events')]
    
    with op.batch_alter_table('financial_events') as batch_op:
        if 'event_type' in columns and 'type' not in columns:
            batch_op.alter_column('event_type', new_column_name='type')
        if 'refunds' not in columns:
            batch_op.add_column(sa.Column('refunds', sa.Float(), server_default='0.0'))

