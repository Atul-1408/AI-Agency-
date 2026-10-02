"""Add rejected_by column to outreach_drafts table

Revision ID: 0005_draft_rejected_by
Revises: 0004_phase3_outreach
Create Date: 2026-10-02 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005_draft_rejected_by'
down_revision: Union[str, None] = '0004_phase3_outreach'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('outreach_drafts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rejected_by', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('outreach_drafts', schema=None) as batch_op:
        batch_op.drop_column('rejected_by')
