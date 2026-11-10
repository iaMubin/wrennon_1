"""Add indexes for dashboard queue and message history queries

Revision ID: b7e1c4d09a52
Revises: 8c17182a5649
Create Date: 2026-11-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b7e1c4d09a52'
down_revision: Union[str, Sequence[str], None] = '8c17182a5649'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_conversations_queue', 'conversations',
                    ['resolved', 'handoff_active', 'updated_at'], if_not_exists=True)
    op.create_index('ix_conversations_assigned_agent', 'conversations',
                    ['assigned_agent'], if_not_exists=True)
    op.create_index('ix_messages_conversation_created', 'messages',
                    ['conversation_id', 'created_at'], if_not_exists=True)


def downgrade() -> None:
    op.drop_index('ix_messages_conversation_created', table_name='messages', if_exists=True)
    op.drop_index('ix_conversations_assigned_agent', table_name='conversations', if_exists=True)
    op.drop_index('ix_conversations_queue', table_name='conversations', if_exists=True)
