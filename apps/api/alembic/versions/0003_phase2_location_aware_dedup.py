"""Phase 2 location-aware deduplication and index adjustment

Revision ID: 0003_phase2_dedup
Revises: 0002_phase2
Create Date: 2026-09-30 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_phase2_dedup'
down_revision: Union[str, None] = '0002_phase2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_index('ix_leads_domain')
        batch_op.create_index(batch_op.f('ix_leads_domain'), ['domain'], unique=False)
        batch_op.add_column(sa.Column('google_place_id', sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f('ix_leads_google_place_id'), ['google_place_id'], unique=False)
        batch_op.add_column(sa.Column('city', sa.String(length=100), nullable=True))
        batch_op.create_index(batch_op.f('ix_leads_city'), ['city'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_leads_city'))
        batch_op.drop_column('city')
        batch_op.drop_index(batch_op.f('ix_leads_google_place_id'))
        batch_op.drop_column('google_place_id')
        batch_op.drop_index(batch_op.f('ix_leads_domain'))
        batch_op.create_index('ix_leads_domain', ['domain'], unique=True)
