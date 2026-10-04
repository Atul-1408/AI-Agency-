"""Add website_code_generations table

Revision ID: 0017_website_code_generations
Revises: 0016_design_blueprints
Create Date: 2026-10-04 23:00:00.000000

Phase 6 Stage 6.4 — Actual Website Code Generation Engine.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017_website_code_generations'
down_revision: Union[str, None] = '0016_design_blueprints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'website_code_generations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('build_session_id', sa.UUID(), nullable=False),
        sa.Column('website_generation_id', sa.UUID(), nullable=False),
        sa.Column('design_blueprint_id', sa.UUID(), nullable=False),
        sa.Column('approved_prd_id', sa.UUID(), nullable=False),
        sa.Column('source_artifact_id', sa.UUID(), nullable=True),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('prd_version', sa.Integer(), nullable=False),
        sa.Column('code_generation_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('provider', sa.String(length=100), nullable=False, server_default='mock_code_provider'),
        sa.Column('model', sa.String(length=100), nullable=False, server_default='mock-nextjs-code-v1'),
        sa.Column('source_checksum', sa.String(length=64), nullable=True),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['build_session_id'], ['website_build_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['website_generation_id'], ['website_generations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['design_blueprint_id'], ['design_blueprints.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_prd_id'], ['client_prds.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_artifact_id'], ['website_build_artifacts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_code_generations_session_id', 'website_code_generations', ['build_session_id'], unique=False)
    op.create_index('ix_code_generations_project_id', 'website_code_generations', ['project_id'], unique=False)
    op.create_index('ix_code_generations_blueprint_id', 'website_code_generations', ['design_blueprint_id'], unique=False)
    op.create_index('ix_code_generations_generation_id', 'website_code_generations', ['website_generation_id'], unique=False)
    op.create_index('ix_code_generations_owner_id', 'website_code_generations', ['owner_id'], unique=False)
    op.create_index('ix_code_generations_status', 'website_code_generations', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_code_generations_status', table_name='website_code_generations')
    op.drop_index('ix_code_generations_owner_id', table_name='website_code_generations')
    op.drop_index('ix_code_generations_generation_id', table_name='website_code_generations')
    op.drop_index('ix_code_generations_blueprint_id', table_name='website_code_generations')
    op.drop_index('ix_code_generations_project_id', table_name='website_code_generations')
    op.drop_index('ix_code_generations_session_id', table_name='website_code_generations')
    op.drop_table('website_code_generations')
