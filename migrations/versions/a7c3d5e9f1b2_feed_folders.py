"""Folders: groups of feeds the reader makes by hand

Revision ID: a7c3d5e9f1b2
Revises: 3efe4499b052

Tags were doing this job and could not: a feed carries any number of them, so
a sidebar built from tags is not a set of folders. A folder is a single, named
home for a feed, made and renamed by the reader. Feed tags stay as they were.

Each feed is in at most one folder. Deleting a folder leaves its feeds in
place, unfiled (ON DELETE SET NULL). Names are unique ignoring case, so "Tech"
and "tech" cannot be two identical-looking rows.
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3d5e9f1b2"
down_revision = "3efe4499b052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    op.create_index("uq_folders_lower_name", "folders", [sa.text("lower(name)")], unique=True)
    op.add_column("feeds", sa.Column("folder_id", sa.Integer, nullable=True))
    op.create_foreign_key("fk_feeds_folder_id_folders", "feeds", "folders",
                          ["folder_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_feeds_folder_id_folders", "feeds", type_="foreignkey")
    op.drop_column("feeds", "folder_id")
    op.drop_index("uq_folders_lower_name", table_name="folders")
    op.drop_table("folders")
