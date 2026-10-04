"""Add website_build_sessions and website_build_artifacts tables

Revision ID: 0014_website_build_sessions
Revises: 0013_projects
Create Date: 2026-10-04 18:00:00.000000

Phase 6 Stage 6.1 — AI Website Builder Foundation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0014_website_build_sessions'
down_revision: Union[str, None] = '0013_projects'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. website_build_sessions table
    op.create_table(
        'website_build_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='created'),
        sa.Column('build_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_build_sessions_project_id', 'website_build_sessions', ['project_id'], unique=False)
    op.create_index('ix_build_sessions_owner_id', 'website_build_sessions', ['owner_id'], unique=False)
    op.create_index('ix_build_sessions_status', 'website_build_sessions', ['status'], unique=False)

    # 2. website_build_artifacts table
    op.create_table(
        'website_build_artifacts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('build_session_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('artifact_type', sa.String(length=50), nullable=False),
        sa.Column('artifact_name', sa.String(length=255), nullable=False),
        sa.Column('artifact_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('content_reference', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['build_session_id'], ['website_build_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_build_artifacts_session_id', 'website_build_artifacts', ['build_session_id'], unique=False)
    op.create_index('ix_build_artifacts_project_id', 'website_build_artifacts', ['project_id'], unique=False)
    op.create_index('ix_build_artifacts_type', 'website_build_artifacts', ['artifact_type'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_build_artifacts_type', table_name='website_build_artifacts')
    op.drop_index('ix_build_artifacts_project_id', table_name='website_build_artifacts')
    op.drop_index('ix_build_artifacts_session_id', table_name='website_build_artifacts')
    op.drop_table('website_build_artifacts')

    op.drop_index('ix_build_sessions_status', table_name='website_build_sessions')
    op.drop_index('ix_build_sessions_owner_id', table_name='website_build_sessions')
    op.drop_index('ix_build_sessions_project_id', table_name='website_build_sessions')
    op.drop_table('website_build_sessions')
