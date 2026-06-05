"""api_keys: opaque DB-backed credentials (replace Keycloak offline-token proxy)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-05 00:01:00.000000+00:00

Changes (ADR 0004 rev 2 — "Opaque DB-backed API keys"):
- API keys are no longer Keycloak offline tokens proxied through token exchange.
  The gallery now generates a random secret (``pg_…``), stores only its SHA-256
  hash, and validates by DB lookup. Revocation is a DB update; no Keycloak
  session is involved per key.
- Drop ``keycloak_session_id`` (no Keycloak session backs a key anymore).
- Add ``token_hash`` (unique) — SHA-256 of the issued secret, the lookup key.
- Add ``token_prefix`` — first chars of the secret, shown in the list view so a
  user can tell their keys apart (GitHub-PAT style).
- Add ``scopes`` — space-delimited snapshot of the issuing user's scopes at
  creation time (the key's capabilities).
- Add ``expires_at`` — absolute TTL (365 d), mirroring the previous offline-token
  lifetime.

Existing offline-token metadata rows are not portable to the new model — there
is no recoverable secret to hash — so the table is recreated rather than
migrated in place.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('idx_api_keys_user_id', table_name='api_keys')
    op.drop_table('api_keys')
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('token_prefix', sa.Text(), nullable=False),
        sa.Column('scopes', sa.Text(), nullable=False, server_default=''),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_api_keys_user_id', 'api_keys', ['user_id'])
    op.create_index('idx_api_keys_token_hash', 'api_keys', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_api_keys_token_hash', table_name='api_keys')
    op.drop_index('idx_api_keys_user_id', table_name='api_keys')
    op.drop_table('api_keys')
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('keycloak_session_id', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_api_keys_user_id', 'api_keys', ['user_id'])
