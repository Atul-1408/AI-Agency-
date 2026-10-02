"""Add consumed_oauth_states table and error tracking columns to gmail_accounts

Revision ID: 0006_oauth_states
Revises: 0005_draft_rejected_by
Create Date: 2026-10-02 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0006_oauth_states'
down_revision: Union[str, None] = '0005_draft_rejected_by'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create consumed_oauth_states table
    op.create_table(
        'consumed_oauth_states',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('jti', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_consumed_oauth_states_id', 'consumed_oauth_states', ['id'])
    op.create_index('ix_consumed_oauth_states_jti', 'consumed_oauth_states', ['jti'], unique=True)
    op.create_index('ix_consumed_oauth_states_owner_id', 'consumed_oauth_states', ['owner_id'])
    op.create_index('ix_consumed_oauth_states_expires_at', 'consumed_oauth_states', ['expires_at'])

    # 2. Add error tracking columns to gmail_accounts
    with op.batch_alter_table('gmail_accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_error_code', sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('gmail_accounts', schema=None) as batch_op:
        batch_op.drop_column('last_error_code')
        batch_op.drop_column('last_error_at')

    op.drop_index('ix_consumed_oauth_states_expires_at', table_name='consumed_oauth_states')
    op.drop_index('ix_consumed_oauth_states_owner_id', table_name='consumed_oauth_states')
    op.drop_index('ix_consumed_oauth_states_jti', table_name='consumed_oauth_states')
    op.drop_index('ix_consumed_oauth_states_id', table_name='consumed_oauth_states')
    op.drop_table('consumed_oauth_states')
