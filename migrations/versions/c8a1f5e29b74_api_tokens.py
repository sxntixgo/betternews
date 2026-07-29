"""Per-device API tokens

Session cookies do not suit a native client, so a phone gets a bearer token it
holds and the reader can revoke for one device without signing out elsewhere.

Only the hash is stored: the token is a password.

Revision ID: c8a1f5e29b74
Revises: b3f1c07d4a52
"""
import sqlalchemy as sa
from alembic import op

revision = "c8a1f5e29b74"
down_revision = "b3f1c07d4a52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    # Every request carries the token, so the lookup is on the hot path.
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_table("api_tokens")
