"""Add client_prds and client_prd_requirement_references tables

Revision ID: 0012_client_prds
Revises: 0011_client_requirements
Create Date: 2026-10-04 14:00:00.000000

Phase 5 Stage 5.3 — PRD Generation and Gate 4 Owner Approval.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0012_client_prds'
down_revision: Union[str, None] = '0011_client_requirements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. client_prds table
    op.create_table(
        'client_prds',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('owner_email', sa.String(length=255), nullable=False),
        sa.Column('lead_id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending_approval'),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('executive_summary', sa.Text(), nullable=False),
        sa.Column('business_overview', sa.JSON(), nullable=False),
        sa.Column('goals', sa.JSON(), nullable=False),
        sa.Column('target_audience', sa.JSON(), nullable=True),
        sa.Column('sitemap', sa.JSON(), nullable=False),
        sa.Column('content_requirements', sa.JSON(), nullable=False),
        sa.Column('functionality_requirements', sa.JSON(), nullable=False),
        sa.Column('design_requirements', sa.JSON(), nullable=False),
        sa.Column('branding_requirements', sa.JSON(), nullable=False),
        sa.Column('contact_requirements', sa.JSON(), nullable=False),
        sa.Column('technical_requirements', sa.JSON(), nullable=False),
        sa.Column('timeline', sa.JSON(), nullable=False),
        sa.Column('budget', sa.JSON(), nullable=False),
        sa.Column('assumptions', sa.JSON(), nullable=False),
        sa.Column('open_questions', sa.JSON(), nullable=False),
        sa.Column('requirement_traceability', sa.JSON(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.String(length=255), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by', sa.String(length=255), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['client_conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id', 'version', name='uq_prd_conv_version'),
    )
    op.create_index('ix_client_prds_id', 'client_prds', ['id'])
    op.create_index('ix_client_prds_conv_id', 'client_prds', ['conversation_id'])
    op.create_index('ix_client_prds_owner_email', 'client_prds', ['owner_email'])
    op.create_index('ix_client_prds_status', 'client_prds', ['status'])
    op.create_index('ix_client_prds_lead_id', 'client_prds', ['lead_id'])

    # 2. client_prd_requirement_references table
    op.create_table(
        'client_prd_requirement_references',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('prd_id', sa.UUID(), nullable=False),
        sa.Column('requirement_id', sa.UUID(), nullable=False),
        sa.Column('requirement_version', sa.Integer(), nullable=False),
        sa.Column('section_key', sa.String(length=100), nullable=False),
        sa.Column('source_message_id', sa.UUID(), nullable=True),
        sa.Column('evidence_excerpt', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['prd_id'], ['client_prds.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requirement_id'], ['client_requirements.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_message_id'], ['client_conversation_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_prd_requirement_references_id', 'client_prd_requirement_references', ['id'])
    op.create_index('ix_prd_req_ref_prd_id', 'client_prd_requirement_references', ['prd_id'])
    op.create_index('ix_prd_req_ref_req_id', 'client_prd_requirement_references', ['requirement_id'])


def downgrade() -> None:
    op.drop_index('ix_prd_req_ref_req_id', table_name='client_prd_requirement_references')
    op.drop_index('ix_prd_req_ref_prd_id', table_name='client_prd_requirement_references')
    op.drop_index('ix_client_prd_requirement_references_id', table_name='client_prd_requirement_references')
    op.drop_table('client_prd_requirement_references')

    op.drop_index('ix_client_prds_lead_id', table_name='client_prds')
    op.drop_index('ix_client_prds_status', table_name='client_prds')
    op.drop_index('ix_client_prds_owner_email', table_name='client_prds')
    op.drop_index('ix_client_prds_conv_id', table_name='client_prds')
    op.drop_index('ix_client_prds_id', table_name='client_prds')
    op.drop_table('client_prds')
