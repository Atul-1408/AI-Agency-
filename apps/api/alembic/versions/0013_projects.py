"""Add projects table

Revision ID: 0013_projects
Revises: 0012_client_prds
Create Date: 2026-10-04 17:00:00.000000

Phase 5 Stage 5.4 — Project Creation and Client Intelligence Dashboard.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0013_projects'
down_revision: Union[str, None] = '0012_client_prds'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('lead_id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('approved_prd_id', sa.UUID(), nullable=False),
        sa.Column('prd_version', sa.Integer(), nullable=False),
        sa.Column('project_name', sa.String(length=255), nullable=False),
        sa.Column('project_slug', sa.String(length=255), nullable=False),
        sa.Column('project_status', sa.String(length=50), nullable=False, server_default='ready_for_build'),
        sa.Column('project_source', sa.String(length=50), nullable=False, server_default='approved_prd'),
        sa.Column('created_by', sa.String(length=255), nullable=False),
        sa.Column('phase_metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['client_conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_prd_id'], ['client_prds.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('approved_prd_id', name='uq_projects_approved_prd_id'),
    )
    op.create_index('ix_projects_owner_id', 'projects', ['owner_id'], unique=False)
    op.create_index('ix_projects_lead_id', 'projects', ['lead_id'], unique=False)
    op.create_index('ix_projects_conversation_id', 'projects', ['conversation_id'], unique=False)
    op.create_index('ix_projects_status', 'projects', ['project_status'], unique=False)
    op.create_index('ix_projects_slug', 'projects', ['project_slug'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_projects_slug', table_name='projects')
    op.drop_index('ix_projects_status', table_name='projects')
    op.drop_index('ix_projects_conversation_id', table_name='projects')
    op.drop_index('ix_projects_lead_id', table_name='projects')
    op.drop_index('ix_projects_owner_id', table_name='projects')
    op.drop_table('projects')
