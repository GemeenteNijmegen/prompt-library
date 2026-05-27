"""org_id on users, status enum expansion, prompt_events table

Revision ID: b3c4d5e6f7a8
Revises: 7ba757a49832
Create Date: 2026-05-27 00:00:00.000000+00:00

Changes:
- users.org_id TEXT NOT NULL added; existing rows backfilled with '' (empty
  string sentinel — real org IDs are Keycloak Organization UUIDs, so '' is
  unambiguous as a dev/seed placeholder).
- prompts.status constrained to draft | published_org | published_public |
  archived; existing 'published' rows migrated to 'published_org' (the
  conservative interpretation: visible within own Organisation only).
- prompt_events audit table created with four indexes per PLAN.md §Data Model.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = '7ba757a49832'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add org_id to users.
    #    server_default='' backfills existing dev/seed rows; the auth middleware
    #    always supplies the real value on upsert, so '' only persists if a row
    #    is never touched by an authenticated request.
    op.add_column(
        'users',
        sa.Column('org_id', sa.Text(), nullable=False, server_default=''),
    )

    # 2. Migrate existing 'published' rows before the constraint lands.
    op.execute("UPDATE prompts SET status = 'published_org' WHERE status = 'published'")

    # 3. Add CHECK constraint to prompts.status.
    #    SQLite does not support ADD CONSTRAINT via ALTER TABLE, so batch mode
    #    recreates the table.
    with op.batch_alter_table('prompts', recreate='always') as batch_op:
        batch_op.create_check_constraint(
            'ck_prompts_status',
            "status IN ('draft', 'published_org', 'published_public', 'archived')",
        )

    # 4. Create prompt_events with the four indexes from PLAN.md §Data Model.
    #    entity_id is TEXT (not INT) to accommodate non-integer IDs such as
    #    image storage keys.
    op.create_table(
        'prompt_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=False),
        sa.Column('actor_org_id', sa.Text(), nullable=False),
        sa.Column('client_id', sa.Text(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_prompt_events_actor_user',
        'prompt_events',
        ['actor_user_id', 'created_at'],
    )
    op.create_index(
        'idx_prompt_events_actor_org',
        'prompt_events',
        ['actor_org_id', 'created_at'],
    )
    op.create_index(
        'idx_prompt_events_entity',
        'prompt_events',
        ['entity_type', 'entity_id', 'created_at'],
    )
    op.create_index(
        'idx_prompt_events_created_at',
        'prompt_events',
        ['created_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_prompt_events_created_at', table_name='prompt_events')
    op.drop_index('idx_prompt_events_entity', table_name='prompt_events')
    op.drop_index('idx_prompt_events_actor_org', table_name='prompt_events')
    op.drop_index('idx_prompt_events_actor_user', table_name='prompt_events')
    op.drop_table('prompt_events')

    # Remove the CHECK constraint; batch recreates the table in SQLite.
    with op.batch_alter_table('prompts', recreate='always') as batch_op:
        batch_op.drop_constraint('ck_prompts_status', type_='check')

    # Revert status values: published_org and published_public both collapse
    # back to 'published' (the only published state in the previous schema).
    op.execute(
        "UPDATE prompts SET status = 'published' "
        "WHERE status IN ('published_org', 'published_public')"
    )

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('org_id')
