"""Add follow_up_sequence_id and follow_up_step_id to outreach_drafts

Revision ID: 0009_follow_up_draft_fields
Revises: 0008_inbound_messages
Create Date: 2026-10-03 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009_follow_up_draft_fields'
down_revision: Union[str, None] = '0008_inbound_messages'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('outreach_drafts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('follow_up_sequence_id', sa.UUID(), nullable=True))
        batch_op.add_column(sa.Column('follow_up_step_id', sa.UUID(), nullable=True))
        batch_op.create_foreign_key(
            'fk_outreach_drafts_follow_up_seq',
            'follow_up_sequences',
            ['follow_up_sequence_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_outreach_drafts_follow_up_step',
            'follow_up_steps',
            ['follow_up_step_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_index('ix_outreach_drafts_follow_up_sequence_id', ['follow_up_sequence_id'])
        batch_op.create_index('ix_outreach_drafts_follow_up_step_id', ['follow_up_step_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('outreach_drafts', schema=None) as batch_op:
        batch_op.drop_index('ix_outreach_drafts_follow_up_step_id')
        batch_op.drop_index('ix_outreach_drafts_follow_up_sequence_id')
        batch_op.drop_constraint('fk_outreach_drafts_follow_up_step', type_='foreignkey')
        batch_op.drop_constraint('fk_outreach_drafts_follow_up_seq', type_='foreignkey')
        batch_op.drop_column('follow_up_step_id')
        batch_op.drop_column('follow_up_sequence_id')
