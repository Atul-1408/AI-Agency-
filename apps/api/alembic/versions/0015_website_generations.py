"""Add website_generations table

Revision ID: 0015_website_generations
Revises: 0014_website_build_sessions
Create Date: 2026-10-04 22:00:00.000000

Phase 6 Stage 6.2 — AI Website Generation Engine Foundation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0015_website_generations'
down_revision: Union[str, None] = '0014_website_build_sessions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'website_generations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('build_session_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('source_prd_id', sa.UUID(), nullable=False),
        sa.Column('source_prd_version', sa.Integer(), nullable=False),
        sa.Column('generation_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('specification_artifact_id', sa.UUID(), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['build_session_id'], ['website_build_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_prd_id'], ['client_prds.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['specification_artifact_id'], ['website_build_artifacts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_website_generations_session_id', 'website_generations', ['build_session_id'], unique=False)
    op.create_index('ix_website_generations_project_id', 'website_generations', ['project_id'], unique=False)
    op.create_index('ix_website_generations_owner_id', 'website_generations', ['owner_id'], unique=False)
    op.create_index('ix_website_generations_status', 'website_generations', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_website_generations_status', table_name='website_generations')
    op.drop_index('ix_website_generations_owner_id', table_name='website_generations')
    op.drop_index('ix_website_generations_project_id', table_name='website_generations')
    op.drop_index('ix_website_generations_session_id', table_name='website_generations')
    op.drop_table('website_generations')
