"""Add website_qa_runs and website_qa_findings tables

Revision ID: 0019_website_qa
Revises: 0018_website_previews_and_edits
Create Date: 2026-10-14 23:00:00.000000

Phase 7 — Automated QA Agent & Evaluator Engine.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0019_website_qa'
down_revision: Union[str, None] = '0018_website_previews_and_edits'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. website_qa_runs
    op.create_table(
        'website_qa_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('build_session_id', sa.UUID(), nullable=False),
        sa.Column('source_generation_id', sa.UUID(), nullable=False),
        sa.Column('target_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='ready_for_qa'),
        sa.Column('total_checks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('passed_checks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_checks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('warning_checks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_checks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['build_session_id'], ['website_build_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_generation_id'], ['website_code_generations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qa_runs_project_id', 'website_qa_runs', ['project_id'], unique=False)
    op.create_index('ix_qa_runs_session_id', 'website_qa_runs', ['build_session_id'], unique=False)
    op.create_index('ix_qa_runs_generation_id', 'website_qa_runs', ['source_generation_id'], unique=False)
    op.create_index('ix_qa_runs_owner_id', 'website_qa_runs', ['owner_id'], unique=False)
    op.create_index('ix_qa_runs_status', 'website_qa_runs', ['status'], unique=False)

    # 2. website_qa_findings
    op.create_table(
        'website_qa_findings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('qa_run_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('affected_route', sa.String(length=255), nullable=False, server_default='/'),
        sa.Column('affected_file', sa.String(length=255), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('reproduction_steps', sa.Text(), nullable=True),
        sa.Column('suggested_repair', sa.Text(), nullable=True),
        sa.Column('is_repaired', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('repaired_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('repaired_in_version', sa.Integer(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['qa_run_id'], ['website_qa_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qa_findings_run_id', 'website_qa_findings', ['qa_run_id'], unique=False)
    op.create_index('ix_qa_findings_project_id', 'website_qa_findings', ['project_id'], unique=False)
    op.create_index('ix_qa_findings_severity', 'website_qa_findings', ['severity'], unique=False)
    op.create_index('ix_qa_findings_category', 'website_qa_findings', ['category'], unique=False)
    op.create_index('ix_qa_findings_is_repaired', 'website_qa_findings', ['is_repaired'], unique=False)


def downgrade() -> None:
    op.drop_table('website_qa_findings')
    op.drop_table('website_qa_runs')
