"""Add agent_workflows and workflow_step_records tables

Revision ID: 0021_agent_workflow
Revises: 0020_website_deployment
Create Date: 2026-10-15 12:45:00.000000

Phase 9 — Complete Agent Workflow Orchestration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0021_agent_workflow'
down_revision: Union[str, None] = '0020_website_deployment'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_workflows',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('mode', sa.String(length=50), nullable=False, server_default='supervised'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='created'),
        sa.Column('current_stage', sa.String(length=100), nullable=False, server_default='lead_discovery'),
        sa.Column('completed_stages', sa.JSON(), nullable=False),
        sa.Column('pending_stages', sa.JSON(), nullable=False),
        sa.Column('stage_data', sa.JSON(), nullable=False),
        sa.Column('current_approval_id', sa.UUID(), nullable=True),
        sa.Column('error_state', sa.JSON(), nullable=True),
        sa.Column('is_dry_run', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['current_approval_id'], ['approval_requests.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_workflows_owner_id', 'agent_workflows', ['owner_id'], unique=False)
    op.create_index('ix_agent_workflows_status', 'agent_workflows', ['status'], unique=False)
    op.create_index('ix_agent_workflows_current_stage', 'agent_workflows', ['current_stage'], unique=False)
    op.create_index('ix_agent_workflows_idempotency_key', 'agent_workflows', ['idempotency_key'], unique=False)

    op.create_table(
        'workflow_step_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('stage', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('input_snapshot', sa.JSON(), nullable=True),
        sa.Column('output_snapshot', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('is_dry_run', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['workflow_id'], ['agent_workflows.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_workflow_step_records_workflow_id', 'workflow_step_records', ['workflow_id'], unique=False)
    op.create_index('ix_workflow_step_records_stage', 'workflow_step_records', ['stage'], unique=False)


def downgrade() -> None:
    op.drop_table('workflow_step_records')
    op.drop_table('agent_workflows')
