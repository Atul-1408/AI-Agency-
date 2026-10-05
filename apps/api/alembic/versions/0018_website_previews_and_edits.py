"""Add website_previews, website_edit_sessions, and website_edit_versions tables

Revision ID: 0018_website_previews_and_edits
Revises: 0017_website_code_generations
Create Date: 2026-10-04 23:45:00.000000

Phase 6 Stage 6.5 — Live Preview + Iterative Website Editing Engine.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0018_website_previews_and_edits'
down_revision: Union[str, None] = '0017_website_code_generations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. website_previews
    op.create_table(
        'website_previews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('build_session_id', sa.UUID(), nullable=False),
        sa.Column('code_generation_id', sa.UUID(), nullable=False),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='created'),
        sa.Column('preview_token', sa.String(length=64), nullable=False),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('process_id', sa.Integer(), nullable=True),
        sa.Column('workspace_reference', sa.String(length=500), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['build_session_id'], ['website_build_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['code_generation_id'], ['website_code_generations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_website_previews_project_id', 'website_previews', ['project_id'], unique=False)
    op.create_index('ix_website_previews_session_id', 'website_previews', ['build_session_id'], unique=False)
    op.create_index('ix_website_previews_code_generation_id', 'website_previews', ['code_generation_id'], unique=False)
    op.create_index('ix_website_previews_token', 'website_previews', ['preview_token'], unique=True)
    op.create_index('ix_website_previews_owner_id', 'website_previews', ['owner_id'], unique=False)
    op.create_index('ix_website_previews_status', 'website_previews', ['status'], unique=False)

    # 2. website_edit_sessions
    op.create_table(
        'website_edit_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('preview_id', sa.UUID(), nullable=True),
        sa.Column('base_code_generation_id', sa.UUID(), nullable=False),
        sa.Column('base_version', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('owner_request', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['preview_id'], ['website_previews.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['base_code_generation_id'], ['website_code_generations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_website_edit_sessions_project_id', 'website_edit_sessions', ['project_id'], unique=False)
    op.create_index('ix_website_edit_sessions_preview_id', 'website_edit_sessions', ['preview_id'], unique=False)
    op.create_index('ix_website_edit_sessions_base_generation_id', 'website_edit_sessions', ['base_code_generation_id'], unique=False)
    op.create_index('ix_website_edit_sessions_owner_id', 'website_edit_sessions', ['owner_id'], unique=False)
    op.create_index('ix_website_edit_sessions_status', 'website_edit_sessions', ['status'], unique=False)

    # 3. website_edit_versions
    op.create_table(
        'website_edit_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('edit_session_id', sa.UUID(), nullable=True),
        sa.Column('source_generation_id', sa.UUID(), nullable=False),
        sa.Column('parent_version', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('changed_files', sa.JSON(), nullable=False),
        sa.Column('diff_summary', sa.Text(), nullable=True),
        sa.Column('source_checksum', sa.String(length=64), nullable=False),
        sa.Column('artifact_id', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['edit_session_id'], ['website_edit_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_generation_id'], ['website_code_generations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['artifact_id'], ['website_build_artifacts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_website_edit_versions_project_id', 'website_edit_versions', ['project_id'], unique=False)
    op.create_index('ix_website_edit_versions_session_id', 'website_edit_versions', ['edit_session_id'], unique=False)
    op.create_index('ix_website_edit_versions_generation_id', 'website_edit_versions', ['source_generation_id'], unique=False)
    op.create_index('ix_website_edit_versions_version', 'website_edit_versions', ['project_id', 'version'], unique=False)
    op.create_index('ix_website_edit_versions_owner_id', 'website_edit_versions', ['owner_id'], unique=False)
    op.create_index('ix_website_edit_versions_is_active', 'website_edit_versions', ['is_active'], unique=False)


def downgrade() -> None:
    op.drop_table('website_edit_versions')
    op.drop_table('website_edit_sessions')
    op.drop_table('website_previews')
