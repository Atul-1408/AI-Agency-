"""Add inbound_messages table

Revision ID: 0008_inbound_messages
Revises: 0007_follow_up_sequences
Create Date: 2026-10-03 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008_inbound_messages'
down_revision: Union[str, None] = '0007_follow_up_sequences'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'inbound_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('gmail_message_id', sa.String(length=255), nullable=False),
        sa.Column('gmail_thread_id', sa.String(length=255), nullable=False),
        sa.Column('sender_email', sa.String(length=255), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('snippet', sa.String(length=1000), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('matched_outreach_message_id', sa.UUID(), nullable=True),
        sa.Column('matched_lead_id', sa.UUID(), nullable=True),
        sa.Column('matched_sequence_id', sa.UUID(), nullable=True),
        sa.Column('processing_status', sa.String(length=50), nullable=False, server_default='PROCESSED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['matched_outreach_message_id'], ['outreach_messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['matched_lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['matched_sequence_id'], ['follow_up_sequences.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_inbound_messages_id', 'inbound_messages', ['id'])
    op.create_index('ix_inbound_messages_gmail_message_id', 'inbound_messages', ['gmail_message_id'], unique=True)
    op.create_index('ix_inbound_messages_gmail_thread_id', 'inbound_messages', ['gmail_thread_id'])
    op.create_index('ix_inbound_messages_sender_email', 'inbound_messages', ['sender_email'])
    op.create_index('ix_inbound_messages_matched_lead_id', 'inbound_messages', ['matched_lead_id'])
    op.create_index('ix_inbound_messages_matched_sequence_id', 'inbound_messages', ['matched_sequence_id'])
    op.create_index('ix_inbound_messages_matched_outreach_message_id', 'inbound_messages', ['matched_outreach_message_id'])
    op.create_index('ix_inbound_messages_processing_status', 'inbound_messages', ['processing_status'])
    op.create_index('ix_inbound_msg_thread', 'inbound_messages', ['gmail_thread_id'])
    op.create_index('ix_inbound_msg_sender', 'inbound_messages', ['sender_email'])
    op.create_index('ix_inbound_msg_lead', 'inbound_messages', ['matched_lead_id'])
    op.create_index('ix_inbound_msg_seq', 'inbound_messages', ['matched_sequence_id'])


def downgrade() -> None:
    op.drop_index('ix_inbound_msg_seq', table_name='inbound_messages')
    op.drop_index('ix_inbound_msg_lead', table_name='inbound_messages')
    op.drop_index('ix_inbound_msg_sender', table_name='inbound_messages')
    op.drop_index('ix_inbound_msg_thread', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_processing_status', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_matched_outreach_message_id', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_matched_sequence_id', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_matched_lead_id', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_sender_email', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_gmail_thread_id', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_gmail_message_id', table_name='inbound_messages')
    op.drop_index('ix_inbound_messages_id', table_name='inbound_messages')
    op.drop_table('inbound_messages')
