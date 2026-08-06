"""What kind of story an article is, alongside what it is about

Revision ID: f1a7d92c4e83
Revises: e5c2a83f7b19

Topic affinity could not separate `boca-juniors`: 28 likes and 30 dislikes, 48%,
noise. The subject was never the axis -- fixture listings and transfer news are
the same subject and opposite value to this reader. Broadcast-listing pieces run
a 12.5% like-rate against 39.4% for everything else.

`kind` is a closed vocabulary (app/kinds.py) so the same article shape gets the
same label every time; topics are open and there are 763 of them, which is right
for subjects and wrong here.

Left NULL for existing rows. Backfilling would mean re-running the tagger over
19,634 articles, and affinity ignores a kind it has too few votes for anyway --
so it fills in as articles are scored, and starts counting once it has evidence.
"""

import sqlalchemy as sa
from alembic import op

revision = "f1a7d92c4e83"
down_revision = "e5c2a83f7b19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("kind", sa.Text(), nullable=True))
    op.add_column("votes", sa.Column("kind_snapshot", sa.Text(), nullable=True))
    # Affinity groups by it on every scoring run.
    op.create_index("ix_articles_kind", "articles", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_articles_kind", table_name="articles")
    op.drop_column("votes", "kind_snapshot")
    op.drop_column("articles", "kind")
