"""Topics on the vote, so affinity survives retention

Revision ID: e5c2a83f7b19
Revises: d4b8e91c37a2

Topic affinity -- the reader's own like-rate per topic -- is computed from
votes, and it measured far better than the model's relevance score on the
owner's 2,149 votes (AUC 0.756 against 0.524, held out 5-fold). Reading the
topics back off `articles` would mean that signal decayed every time retention
ran: `votes.article_id` is ON DELETE SET NULL, so a pruned article takes its
topics with it.

Snapshotting them on the vote is the same decision already made for
`title_snapshot` and `summary_snapshot`, for the same reason.

Backfilled from the articles that are still here. Anything already pruned is
lost, which is precisely the leak this closes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "e5c2a83f7b19"
down_revision = "d4b8e91c37a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("votes", sa.Column("topics_snapshot", ARRAY(sa.Text()), nullable=True))
    op.execute("""
        UPDATE votes v
           SET topics_snapshot = a.topics
          FROM articles a
         WHERE a.id = v.article_id
           AND a.topics IS NOT NULL
           AND cardinality(a.topics) > 0
    """)


def downgrade() -> None:
    op.drop_column("votes", "topics_snapshot")
