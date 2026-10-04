"""Add client_conversations and client_conversation_messages tables

Revision ID: 0010_client_conversations
Revises: 0009_follow_up_draft_fields
Create Date: 2026-10-03 01:12:00.000000

Phase 5 Stage 5.1 — Conversation Foundation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010_client_conversations'
down_revision: Union[str, None] = '0009_follow_up_draft_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. client_conversations table
    op.create_table(
        'client_conversations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('lead_id', sa.UUID(), nullable=False),
        sa.Column('inbound_message_id', sa.UUID(), nullable=True),
        sa.Column('owner_email', sa.String(length=255), nullable=False),
        sa.Column('gmail_thread_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='initiated'),
        # Thread snapshot metadata
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('message_count', sa.Integer(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        # Owner annotation (Stage 5.2+ usage; columns present now to avoid later migration churn)
        sa.Column('intent', sa.String(length=50), nullable=True),
        sa.Column('budget_signal', sa.String(length=500), nullable=True),
        sa.Column('timeline_signal', sa.String(length=500), nullable=True),
        sa.Column('owner_notes', sa.Text(), nullable=True),
        # Gate 3 state (Stage 5.2+)
        sa.Column('requirements_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('requirements_reviewed_by', sa.String(length=255), nullable=True),
        # Standard timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inbound_message_id'], ['inbound_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lead_id', 'gmail_thread_id', name='uq_conversation_lead_thread'),
    )
    op.create_index('ix_client_conversations_id', 'client_conversations', ['id'])
    op.create_index('ix_client_conversations_lead_id', 'client_conversations', ['lead_id'])
    op.create_index('ix_client_conversations_inbound_message_id', 'client_conversations', ['inbound_message_id'])
    op.create_index('ix_client_conversations_owner_email', 'client_conversations', ['owner_email'])
    op.create_index('ix_client_conv_thread', 'client_conversations', ['gmail_thread_id'])
    op.create_index('ix_client_conv_status', 'client_conversations', ['status'])
    op.create_index('ix_client_conv_lead_status', 'client_conversations', ['lead_id', 'status'])

    # 2. client_conversation_messages table
    op.create_table(
        'client_conversation_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('gmail_message_id', sa.String(length=255), nullable=False),
        sa.Column('gmail_thread_id', sa.String(length=255), nullable=False),
        sa.Column('sender_email', sa.String(length=255), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('direction', sa.String(length=20), nullable=False),
        # SECURITY: UNTRUSTED EXTERNAL DATA — plain text, stripped HTML, capped at 10 000 chars
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        # Standard timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['client_conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('gmail_message_id', name='uq_conv_msg_gmail_id'),
    )
    op.create_index('ix_client_conversation_messages_id', 'client_conversation_messages', ['id'])
    op.create_index('ix_conv_msg_conversation', 'client_conversation_messages', ['conversation_id'])
    op.create_index('ix_conv_msg_gmail_msg_id', 'client_conversation_messages', ['gmail_message_id'])
    op.create_index('ix_conv_msg_received_at', 'client_conversation_messages', ['received_at'])
    op.create_index('ix_conv_msg_direction', 'client_conversation_messages', ['conversation_id', 'direction'])


def downgrade() -> None:
    op.drop_index('ix_conv_msg_direction', table_name='client_conversation_messages')
    op.drop_index('ix_conv_msg_received_at', table_name='client_conversation_messages')
    op.drop_index('ix_conv_msg_gmail_msg_id', table_name='client_conversation_messages')
    op.drop_index('ix_conv_msg_conversation', table_name='client_conversation_messages')
    op.drop_index('ix_client_conversation_messages_id', table_name='client_conversation_messages')
    op.drop_table('client_conversation_messages')

    op.drop_index('ix_client_conv_lead_status', table_name='client_conversations')
    op.drop_index('ix_client_conv_status', table_name='client_conversations')
    op.drop_index('ix_client_conv_thread', table_name='client_conversations')
    op.drop_index('ix_client_conversations_owner_email', table_name='client_conversations')
    op.drop_index('ix_client_conversations_inbound_message_id', table_name='client_conversations')
    op.drop_index('ix_client_conversations_lead_id', table_name='client_conversations')
    op.drop_index('ix_client_conversations_id', table_name='client_conversations')
    op.drop_table('client_conversations')
