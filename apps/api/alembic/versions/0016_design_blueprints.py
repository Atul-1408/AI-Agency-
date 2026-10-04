"""Add design_blueprints table

Revision ID: 0016_design_blueprints
Revises: 0015_website_generations
Create Date: 2026-10-04 22:30:00.000000

Phase 6 Stage 6.3 — Design System + Site Architecture Blueprint Engine.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016_design_blueprints'
down_revision: Union[str, None] = '0015_website_generations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'design_blueprints',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('build_session_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('source_generation_id', sa.UUID(), nullable=False),
        sa.Column('source_generation_version', sa.Integer(), nullable=False),
        sa.Column('blueprint_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
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
        sa.ForeignKeyConstraint(['source_generation_id'], ['website_generations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['specification_artifact_id'], ['website_build_artifacts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_design_blueprints_generation_id', 'design_blueprints', ['source_generation_id'], unique=False)
    op.create_index('ix_design_blueprints_session_id', 'design_blueprints', ['build_session_id'], unique=False)
    op.create_index('ix_design_blueprints_project_id', 'design_blueprints', ['project_id'], unique=False)
    op.create_index('ix_design_blueprints_owner_id', 'design_blueprints', ['owner_id'], unique=False)
    op.create_index('ix_design_blueprints_status', 'design_blueprints', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_design_blueprints_status', table_name='design_blueprints')
    op.drop_index('ix_design_blueprints_owner_id', table_name='design_blueprints')
    op.drop_index('ix_design_blueprints_project_id', table_name='design_blueprints')
    op.drop_index('ix_design_blueprints_session_id', table_name='design_blueprints')
    op.drop_index('ix_design_blueprints_generation_id', table_name='design_blueprints')
    op.drop_table('design_blueprints')
