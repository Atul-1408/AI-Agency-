"""Phase 2 leads and lead research schema

Revision ID: 0002_phase2
Revises: 0001_phase1
Create Date: 2026-09-30 14:16:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002_phase2'
down_revision: Union[str, None] = '0001_phase1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'leads',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('website_url', sa.String(length=1000), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('email_verification_status', sa.String(length=50), nullable=False, server_default='unverified'),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('industry', sa.String(length=100), nullable=True),
        sa.Column('qualification_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='discovered'),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('source_query', sa.String(length=255), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leads_id'), 'leads', ['id'], unique=False)
    op.create_index(op.f('ix_leads_company_name'), 'leads', ['company_name'], unique=False)
    op.create_index(op.f('ix_leads_domain'), 'leads', ['domain'], unique=True)
    op.create_index(op.f('ix_leads_phone'), 'leads', ['phone'], unique=False)
    op.create_index(op.f('ix_leads_email'), 'leads', ['email'], unique=False)
    op.create_index(op.f('ix_leads_industry'), 'leads', ['industry'], unique=False)
    op.create_index(op.f('ix_leads_qualification_score'), 'leads', ['qualification_score'], unique=False)
    op.create_index(op.f('ix_leads_status'), 'leads', ['status'], unique=False)
    op.create_index(op.f('ix_leads_source_type'), 'leads', ['source_type'], unique=False)

    op.create_table(
        'lead_research',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('lead_id', sa.Uuid(), nullable=False),
        sa.Column('has_website', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_responsive', sa.Boolean(), nullable=True),
        sa.Column('has_ssl', sa.Boolean(), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('load_time_ms', sa.Integer(), nullable=True),
        sa.Column('copyright_year', sa.Integer(), nullable=True),
        sa.Column('tech_stack', sa.JSON(), nullable=True),
        sa.Column('audit_findings', sa.JSON(), nullable=True),
        sa.Column('research_notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lead_research_id'), 'lead_research', ['id'], unique=False)
    op.create_index(op.f('ix_lead_research_lead_id'), 'lead_research', ['lead_id'], unique=True)


def downgrade() -> None:
    op.drop_table('lead_research')
    op.drop_table('leads')
