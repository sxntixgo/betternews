"""Record when a reader was last here, for the "what you missed" strip

Revision ID: 3efe4499b052
Revises: f1a7d92c4e83

`last_login_at` already exists and is not this: it moves only on sign-in, and
the session cookie lasts 90 days, so "since you last signed in" can be months
old -- the wrong question for a strip that wants "since you last read".

`last_seen_at` is touched on every `GET /digest/meta` call, which is how the
strip learns what to say without generating the LLM briefing it links to.
"""

import sqlalchemy as sa
from alembic import op

revision = "3efe4499b052"
down_revision = "f1a7d92c4e83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "last_seen_at")
