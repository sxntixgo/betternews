"""One preference profile per reader

The profile is built from votes, and votes have always been per-user. The table
was not: a singleton row meant one reader's likes and dislikes shaped what
everyone else was shown, and there was no way to see your own taste separately
from anybody else's.

The existing row is kept and assigned to the lowest user id -- the owner, whose
votes almost certainly produced it. Discarding it would throw away a profile
that took real reading to build.

Revision ID: d4b8e91c37a2
Revises: c8a1f5e29b74
"""
import sqlalchemy as sa
from alembic import op

revision = "d4b8e91c37a2"
down_revision = "c8a1f5e29b74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    owner = conn.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()

    op.add_column("preferences", sa.Column("user_id", sa.Integer(), nullable=True))
    op.drop_constraint("singleton", "preferences", type_="check")

    if owner is not None:
        conn.execute(sa.text("UPDATE preferences SET user_id = :u WHERE user_id IS NULL"),
                     {"u": owner})
        # A profile with no owner cannot be reached by anyone.
        conn.execute(sa.text("DELETE FROM preferences WHERE user_id IS NULL"))
    else:
        # No users yet, so nothing could have voted; the row is an empty default.
        conn.execute(sa.text("DELETE FROM preferences"))

    op.alter_column("preferences", "user_id", nullable=False)

    # user_id becomes the key. `id` was declared autoincrement=False and only
    # ever held the literal 1, so it has no sequence behind it -- inserting a
    # second row fails on a null id. With exactly one profile per reader there
    # is nothing for a surrogate key to do.
    # Names follow the metadata naming convention in app/models.py -- pk_%(table)s
    # and fk_%(table)s_%(column)s_%(referred)s -- not Postgres's defaults.
    op.drop_constraint("pk_preferences", "preferences", type_="primary")
    op.drop_column("preferences", "id")
    op.create_primary_key("pk_preferences", "preferences", ["user_id"])
    op.create_foreign_key("fk_preferences_user_id_users", "preferences", "users",
                          ["user_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    conn = op.get_bind()
    # Collapsing back to a singleton has to pick a winner; the owner's is the
    # one the old code served.
    conn.execute(sa.text(
        "DELETE FROM preferences WHERE user_id <> (SELECT min(user_id) FROM preferences)"))
    op.drop_constraint("fk_preferences_user_id_users", "preferences", type_="foreignkey")
    op.drop_constraint("pk_preferences", "preferences", type_="primary")
    op.add_column("preferences", sa.Column("id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE preferences SET id = 1"))
    op.alter_column("preferences", "id", nullable=False)
    op.create_primary_key("pk_preferences", "preferences", ["id"])
    op.drop_column("preferences", "user_id")
    op.create_check_constraint("singleton", "preferences", "id = 1")
