"""Add client_requirements, client_requirement_evidence, client_requirement_versions, and client_clarifications tables

Revision ID: 0011_client_requirements
Revises: 0010_client_conversations
Create Date: 2026-10-03 20:30:00.000000

Phase 5 Stage 5.2 — Client Requirement Extraction & Intelligence.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011_client_requirements'
down_revision: Union[str, None] = '0010_client_conversations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. client_requirements table
    op.create_table(
        'client_requirements',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('owner_email', sa.String(length=255), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('category_group', sa.String(length=50), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='identified'),
        sa.Column('confidence', sa.String(length=50), nullable=False, server_default='medium'),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['client_conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id', 'key', name='uq_conv_req_key'),
    )
    op.create_index('ix_client_requirements_id', 'client_requirements', ['id'])
    op.create_index('ix_client_requirements_conversation_id', 'client_requirements', ['conversation_id'])
    op.create_index('ix_client_requirements_owner_email', 'client_requirements', ['owner_email'])
    op.create_index('ix_client_requirements_key', 'client_requirements', ['key'])
    op.create_index('ix_client_req_conv_key', 'client_requirements', ['conversation_id', 'key'])
    op.create_index('ix_client_req_status', 'client_requirements', ['status'])
    op.create_index('ix_client_req_category', 'client_requirements', ['category_group'])

    # 2. client_requirement_evidence table
    op.create_table(
        'client_requirement_evidence',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('requirement_id', sa.UUID(), nullable=False),
        sa.Column('conversation_message_id', sa.UUID(), nullable=False),
        sa.Column('source_message_direction', sa.String(length=20), nullable=False),
        sa.Column('excerpt', sa.Text(), nullable=False),
        sa.Column('extraction_method', sa.String(length=50), nullable=False, server_default='deterministic'),
        sa.Column('confidence', sa.String(length=50), nullable=False, server_default='medium'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['requirement_id'], ['client_requirements.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_message_id'], ['client_conversation_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('requirement_id', 'conversation_message_id', 'excerpt', name='uq_req_evidence_unique'),
    )
    op.create_index('ix_client_requirement_evidence_id', 'client_requirement_evidence', ['id'])
    op.create_index('ix_req_evidence_req_id', 'client_requirement_evidence', ['requirement_id'])
    op.create_index('ix_req_evidence_msg_id', 'client_requirement_evidence', ['conversation_message_id'])

    # 3. client_requirement_versions table
    op.create_table(
        'client_requirement_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('requirement_id', sa.UUID(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('old_value', sa.JSON(), nullable=True),
        sa.Column('new_value', sa.JSON(), nullable=True),
        sa.Column('change_reason', sa.String(length=255), nullable=True),
        sa.Column('source_message_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['requirement_id'], ['client_requirements.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_message_id'], ['client_conversation_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_requirement_versions_id', 'client_requirement_versions', ['id'])
    op.create_index('ix_req_version_req_ver', 'client_requirement_versions', ['requirement_id', 'version_number'])

    # 4. client_clarifications table
    op.create_table(
        'client_clarifications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('owner_email', sa.String(length=255), nullable=False),
        sa.Column('category_group', sa.String(length=50), nullable=False),
        sa.Column('requirement_key', sa.String(length=100), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['client_conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id', 'requirement_key', name='uq_conv_clarification_key'),
    )
    op.create_index('ix_client_clarifications_id', 'client_clarifications', ['id'])
    op.create_index('ix_conv_clarification_conv', 'client_clarifications', ['conversation_id'])
    op.create_index('ix_conv_clarification_status', 'client_clarifications', ['status'])


def downgrade() -> None:
    op.drop_index('ix_conv_clarification_status', table_name='client_clarifications')
    op.drop_index('ix_conv_clarification_conv', table_name='client_clarifications')
    op.drop_index('ix_client_clarifications_id', table_name='client_clarifications')
    op.drop_table('client_clarifications')

    op.drop_index('ix_req_version_req_ver', table_name='client_requirement_versions')
    op.drop_index('ix_client_requirement_versions_id', table_name='client_requirement_versions')
    op.drop_table('client_requirement_versions')

    op.drop_index('ix_req_evidence_msg_id', table_name='client_requirement_evidence')
    op.drop_index('ix_req_evidence_req_id', table_name='client_requirement_evidence')
    op.drop_index('ix_client_requirement_evidence_id', table_name='client_requirement_evidence')
    op.drop_table('client_requirement_evidence')

    op.drop_index('ix_client_req_category', table_name='client_requirements')
    op.drop_index('ix_client_req_status', table_name='client_requirements')
    op.drop_index('ix_client_req_conv_key', table_name='client_requirements')
    op.drop_index('ix_client_requirements_key', table_name='client_requirements')
    op.drop_index('ix_client_requirements_owner_email', table_name='client_requirements')
    op.drop_index('ix_client_requirements_conversation_id', table_name='client_requirements')
    op.drop_index('ix_client_requirements_id', table_name='client_requirements')
    op.drop_table('client_requirements')
