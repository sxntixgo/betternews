"""Decode HTML entities left in stored article titles

Publishers escape twice: the feed XML carries `&amp;#8217;`, the XML parser
hands feedparser `&#8217;`, and nothing decoded the second layer -- so titles
read "Tile&#8217;s best Bluetooth tracker is down to its lowest price".

Ingest now decodes (app.feeds.decode_entities); this repairs what is already
stored. Done in Python rather than SQL because there is no sane way to expand
the full entity table in a REPLACE chain.

Only rows that actually change are written, and only titles -- summaries are
model-generated and clean, and full_text goes through strip_html, which decodes
entities on the way in.

Revision ID: b3f1c07d4a52
Revises: 7e07fa49fd95
"""
from html import unescape

import sqlalchemy as sa
from alembic import op

revision = "b3f1c07d4a52"
down_revision = "7e07fa49fd95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, title, clean_title FROM articles "
        "WHERE title LIKE '%&%;%' OR clean_title LIKE '%&%;%'"
    )).fetchall()

    for row_id, title, clean_title in rows:
        new_title = unescape(title) if title else title
        new_clean = unescape(clean_title) if clean_title else clean_title
        if new_title == title and new_clean == clean_title:
            continue
        conn.execute(
            sa.text("UPDATE articles SET title = :t, clean_title = :c WHERE id = :i"),
            {"t": new_title, "c": new_clean, "i": row_id},
        )


def downgrade() -> None:
    # Re-escaping would corrupt every apostrophe a publisher sent correctly.
    # The decoded text is what the feed meant; there is nothing to go back to.
    pass
