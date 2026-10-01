"""Phase 3 outreach agent schema

Revision ID: 0004_phase3_outreach
Revises: 0003_phase2_dedup
Create Date: 2026-10-01 23:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004_phase3_outreach'
down_revision: Union[str, None] = '0003_phase2_dedup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Outreach Drafts ────────────────────────────────────────────────────
    op.create_table(
        'outreach_drafts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('lead_id', sa.Uuid(), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('body_text', sa.Text(), nullable=False),
        sa.Column('body_html', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='drafted'),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.String(length=255), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_outreach_drafts_id'), 'outreach_drafts', ['id'], unique=False)
    op.create_index(op.f('ix_outreach_drafts_lead_id'), 'outreach_drafts', ['lead_id'], unique=False)
    op.create_index(op.f('ix_outreach_drafts_recipient_email'), 'outreach_drafts', ['recipient_email'], unique=False)
    op.create_index(op.f('ix_outreach_drafts_status'), 'outreach_drafts', ['status'], unique=False)

    # ── 2. Gmail Accounts ─────────────────────────────────────────────────────
    op.create_table(
        'gmail_accounts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False, server_default='owner'),
        sa.Column('google_email', sa.String(length=255), nullable=False),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=False),
        sa.Column('token_created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_token_refresh_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('connection_status', sa.String(length=50), nullable=False, server_default='disconnected'),
        sa.Column('last_health_check', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_gmail_accounts_id'), 'gmail_accounts', ['id'], unique=False)
    op.create_index(op.f('ix_gmail_accounts_owner_id'), 'gmail_accounts', ['owner_id'], unique=False)
    op.create_index(op.f('ix_gmail_accounts_google_email'), 'gmail_accounts', ['google_email'], unique=True)
    op.create_index(op.f('ix_gmail_accounts_connection_status'), 'gmail_accounts', ['connection_status'], unique=False)

    # ── 3. Outreach Messages ──────────────────────────────────────────────────
    op.create_table(
        'outreach_messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('draft_id', sa.Uuid(), nullable=True),
        sa.Column('lead_id', sa.Uuid(), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('gmail_message_id', sa.String(length=255), nullable=True),
        sa.Column('gmail_thread_id', sa.String(length=255), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='sent'),
        sa.ForeignKeyConstraint(['draft_id'], ['outreach_drafts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_outreach_messages_id'), 'outreach_messages', ['id'], unique=False)
    op.create_index(op.f('ix_outreach_messages_draft_id'), 'outreach_messages', ['draft_id'], unique=False)
    op.create_index(op.f('ix_outreach_messages_lead_id'), 'outreach_messages', ['lead_id'], unique=False)
    op.create_index(op.f('ix_outreach_messages_recipient_email'), 'outreach_messages', ['recipient_email'], unique=False)
    op.create_index(op.f('ix_outreach_messages_gmail_message_id'), 'outreach_messages', ['gmail_message_id'], unique=False)
    op.create_index(op.f('ix_outreach_messages_gmail_thread_id'), 'outreach_messages', ['gmail_thread_id'], unique=False)
    op.create_index(op.f('ix_outreach_messages_status'), 'outreach_messages', ['status'], unique=False)

    # ── 4. Send Attempts ──────────────────────────────────────────────────────
    op.create_table(
        'send_attempts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('draft_id', sa.Uuid(), nullable=True),
        sa.Column('lead_id', sa.Uuid(), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('result', sa.String(length=50), nullable=False),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('gmail_message_id', sa.String(length=255), nullable=True),
        sa.Column('gmail_thread_id', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['draft_id'], ['outreach_drafts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_send_attempts_id'), 'send_attempts', ['id'], unique=False)
    op.create_index(op.f('ix_send_attempts_draft_id'), 'send_attempts', ['draft_id'], unique=False)
    op.create_index(op.f('ix_send_attempts_lead_id'), 'send_attempts', ['lead_id'], unique=False)
    op.create_index(op.f('ix_send_attempts_recipient_email'), 'send_attempts', ['recipient_email'], unique=False)
    op.create_index(op.f('ix_send_attempts_attempted_at'), 'send_attempts', ['attempted_at'], unique=False)
    op.create_index(op.f('ix_send_attempts_result'), 'send_attempts', ['result'], unique=False)

    # ── 5. Suppression Records ────────────────────────────────────────────────
    op.create_table(
        'suppression_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('domain', sa.String(length=255), nullable=True),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=100), nullable=False, server_default='system'),
        sa.CheckConstraint(
            "(email IS NOT NULL AND length(email) > 0) OR (domain IS NOT NULL AND length(domain) > 0)",
            name='ck_suppression_target',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_suppression_records_id'), 'suppression_records', ['id'], unique=False)
    op.create_index(op.f('ix_suppression_records_email'), 'suppression_records', ['email'], unique=False)
    op.create_index(op.f('ix_suppression_records_domain'), 'suppression_records', ['domain'], unique=False)
    op.create_index(op.f('ix_suppression_records_reason'), 'suppression_records', ['reason'], unique=False)

    # ── 6. Delivery Events ────────────────────────────────────────────────────
    op.create_table(
        'delivery_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('outreach_message_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('event_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['outreach_message_id'], ['outreach_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_delivery_events_id'), 'delivery_events', ['id'], unique=False)
    op.create_index(op.f('ix_delivery_events_outreach_message_id'), 'delivery_events', ['outreach_message_id'], unique=False)
    op.create_index(op.f('ix_delivery_events_event_type'), 'delivery_events', ['event_type'], unique=False)


def downgrade() -> None:
    # Drop in reverse topological order
    op.drop_table('delivery_events')
    op.drop_table('suppression_records')
    op.drop_table('send_attempts')
    op.drop_table('outreach_messages')
    op.drop_table('gmail_accounts')
    op.drop_table('outreach_drafts')
