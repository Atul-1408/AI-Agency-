"""Add website_deployments table

Revision ID: 0020_website_deployment
Revises: 0019_website_qa
Create Date: 2026-10-14 23:55:00.000000

Phase 8 — Production Deployment & Hosting Integrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0020_website_deployment'
down_revision: Union[str, None] = '0019_website_qa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'website_deployments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('build_session_id', sa.UUID(), nullable=False),
        sa.Column('code_generation_id', sa.UUID(), nullable=False),
        sa.Column('qa_run_id', sa.UUID(), nullable=False),
        sa.Column('source_version', sa.Integer(), nullable=False),
        sa.Column('source_checksum', sa.String(length=64), nullable=False),
        sa.Column('environment', sa.String(length=50), nullable=False, server_default='production'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='ready_for_deployment'),
        sa.Column('provider', sa.String(length=50), nullable=False, server_default='vercel'),
        sa.Column('deployment_url', sa.String(length=1024), nullable=True),
        sa.Column('production_url', sa.String(length=1024), nullable=True),
        sa.Column('custom_domain', sa.String(length=255), nullable=True),
        sa.Column('dns_records', sa.JSON(), nullable=False),
        sa.Column('ssl_status', sa.String(length=50), nullable=False, server_default='unconfigured'),
        sa.Column('github_repo_url', sa.String(length=1024), nullable=True),
        sa.Column('github_repo_name', sa.String(length=255), nullable=True),
        sa.Column('github_branch', sa.String(length=100), nullable=True, server_default='main'),
        sa.Column('github_commit_sha', sa.String(length=64), nullable=True),
        sa.Column('provider_deployment_id', sa.String(length=255), nullable=True),
        sa.Column('build_logs', sa.Text(), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('approval_request_id', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.String(length=255), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['build_session_id'], ['website_build_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['code_generation_id'], ['website_code_generations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['qa_run_id'], ['website_qa_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approval_request_id'], ['approval_requests.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_website_deployments_owner_id', 'website_deployments', ['owner_id'], unique=False)
    op.create_index('ix_website_deployments_project_id', 'website_deployments', ['project_id'], unique=False)
    op.create_index('ix_website_deployments_status', 'website_deployments', ['status'], unique=False)
    op.create_index('ix_website_deployments_code_gen_id', 'website_deployments', ['code_generation_id'], unique=False)
    op.create_index('ix_website_deployments_qa_run_id', 'website_deployments', ['qa_run_id'], unique=False)


def downgrade() -> None:
    op.drop_table('website_deployments')
