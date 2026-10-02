"""Add follow_up_sequences and follow_up_steps tables

Revision ID: 0007_follow_up_sequences
Revises: 0006_oauth_states
Create Date: 2026-10-02 23:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007_follow_up_sequences'
down_revision: Union[str, None] = '0006_oauth_states'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create follow_up_sequences table
    op.create_table(
        'follow_up_sequences',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('lead_id', sa.UUID(), nullable=False),
        sa.Column('outreach_draft_id', sa.UUID(), nullable=True),
        sa.Column('original_message_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('max_steps', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('next_action_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stop_reason', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['outreach_draft_id'], ['outreach_drafts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['original_message_id'], ['outreach_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_follow_up_sequences_id', 'follow_up_sequences', ['id'])
    op.create_index('ix_follow_up_sequences_lead_id', 'follow_up_sequences', ['lead_id'])
    op.create_index('ix_follow_up_sequences_outreach_draft_id', 'follow_up_sequences', ['outreach_draft_id'])
    op.create_index('ix_follow_up_sequences_original_message_id', 'follow_up_sequences', ['original_message_id'])
    op.create_index('ix_follow_up_sequences_status', 'follow_up_sequences', ['status'])
    op.create_index('ix_follow_up_sequences_next_action_at', 'follow_up_sequences', ['next_action_at'])
    op.create_index('ix_followup_seq_lead_status', 'follow_up_sequences', ['lead_id', 'status'])
    op.create_index('ix_followup_seq_status_next_action', 'follow_up_sequences', ['status', 'next_action_at'])
    op.create_index('ix_followup_seq_orig_msg', 'follow_up_sequences', ['original_message_id'])

    # 2. Create follow_up_steps table
    op.create_table(
        'follow_up_steps',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('sequence_id', sa.UUID(), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('delay_hours', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('draft_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['sequence_id'], ['follow_up_sequences.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['draft_id'], ['outreach_drafts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_follow_up_steps_id', 'follow_up_steps', ['id'])
    op.create_index('ix_follow_up_steps_sequence_id', 'follow_up_steps', ['sequence_id'])
    op.create_index('ix_follow_up_steps_draft_id', 'follow_up_steps', ['draft_id'])
    op.create_index('ix_follow_up_steps_status', 'follow_up_steps', ['status'])
    op.create_index('ix_follow_up_steps_scheduled_at', 'follow_up_steps', ['scheduled_at'])
    op.create_index('ix_followup_step_seq_number', 'follow_up_steps', ['sequence_id', 'step_number'], unique=True)
    op.create_index('ix_followup_step_status_scheduled', 'follow_up_steps', ['status', 'scheduled_at'])


def downgrade() -> None:
    op.drop_index('ix_followup_step_status_scheduled', table_name='follow_up_steps')
    op.drop_index('ix_followup_step_seq_number', table_name='follow_up_steps')
    op.drop_index('ix_follow_up_steps_scheduled_at', table_name='follow_up_steps')
    op.drop_index('ix_follow_up_steps_status', table_name='follow_up_steps')
    op.drop_index('ix_follow_up_steps_draft_id', table_name='follow_up_steps')
    op.drop_index('ix_follow_up_steps_sequence_id', table_name='follow_up_steps')
    op.drop_index('ix_follow_up_steps_id', table_name='follow_up_steps')
    op.drop_table('follow_up_steps')

    op.drop_index('ix_followup_seq_orig_msg', table_name='follow_up_sequences')
    op.drop_index('ix_followup_seq_status_next_action', table_name='follow_up_sequences')
    op.drop_index('ix_followup_seq_lead_status', table_name='follow_up_sequences')
    op.drop_index('ix_follow_up_sequences_next_action_at', table_name='follow_up_sequences')
    op.drop_index('ix_follow_up_sequences_status', table_name='follow_up_sequences')
    op.drop_index('ix_follow_up_sequences_original_message_id', table_name='follow_up_sequences')
    op.drop_index('ix_follow_up_sequences_outreach_draft_id', table_name='follow_up_sequences')
    op.drop_index('ix_follow_up_sequences_lead_id', table_name='follow_up_sequences')
    op.drop_index('ix_follow_up_sequences_id', table_name='follow_up_sequences')
    op.drop_table('follow_up_sequences')
