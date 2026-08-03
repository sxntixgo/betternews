"""Schema as SQLAlchemy Core metadata.

Core, not the ORM: `docs/plan.md` deliberately keeps the data layer as plumbing,
and composable Core constructs are what let `app/repo/` enforce a rule like
"every article query takes a user_id" in one place. An ORM session/identity map
would buy nothing here.

Translation notes from the SQLite original (`app/schema.sql`, retained for
reference):

* ISO-8601 ``TEXT`` timestamps  -> ``TIMESTAMP(timezone=True)``. Real ordering
  and comparison, and the Python side passes ``datetime`` objects instead of
  formatting strings.
* ``INTEGER`` 0/1 flags         -> ``Boolean``.
* ``AUTOINCREMENT``             -> identity columns.
* ``COLLATE NOCASE`` on username-> a unique index on ``lower(username)``.
* FTS5 virtual table + 3 triggers -> one generated ``tsvector`` column that
  Postgres maintains itself. Adding a field to the index is now a one-line
  change to the expression rather than a table-and-trigger rebuild.
"""

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Computed, Float, ForeignKey, Index,
    Integer, MetaData, Table, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, TSVECTOR

# Explicit naming convention so Alembic autogenerate produces stable, readable
# constraint names instead of database-assigned ones.
metadata = MetaData(naming_convention={
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})


def _ts(**kw) -> Column:
    return Column(TIMESTAMP(timezone=True), **kw)


users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("username", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False, server_default="user"),
    Column("must_change_password", Boolean, nullable=False, server_default="false"),
    _ts(name="created_at", nullable=False, server_default=func.now()),
    _ts(name="last_login_at"),
    CheckConstraint("role IN ('user','admin')", name="role_valid"),
)
# Case-insensitive uniqueness without the citext extension.
Index("ix_users_username_lower", func.lower(users.c.username), unique=True)


feeds = Table(
    "feeds", metadata,
    Column("id", Integer, primary_key=True),
    Column("url", Text, nullable=False, unique=True),
    Column("title", Text),
    _ts(name="last_polled_at"),
    _ts(name="last_success_at"),
    Column("last_error", Text),
    Column("consecutive_failures", Integer, nullable=False, server_default="0"),
    Column("paused", Boolean, nullable=False, server_default="false"),
    Column("score_threshold", Float),
    Column("etag", Text),
    Column("last_modified", Text),          # opaque HTTP header, not a timestamp
    Column("tags", Text),
)


articles = Table(
    "articles", metadata,
    Column("id", Integer, primary_key=True),
    Column("feed_id", Integer, ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False),
    Column("guid", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("title", Text, nullable=False),
    _ts(name="published_at"),
    Column("raw_snippet", Text),
    Column("feed_content", Text),
    Column("full_text", Text),
    Column("summary", Text),
    Column("clean_title", Text),
    Column("title_was_clickbait", Boolean),
    Column("aside_spans", JSONB),
    Column("topics", ARRAY(Text)),
    Column("cluster_id", Text),
    Column("score", Float),
    Column("score_reason", Text),
    Column("thumbnail_url", Text),
    Column("extract_source", Text),
    # status is now the pipeline lifecycle ONLY. User opinion lives in
    # user_article_state — see the Phase 1 migration.
    Column("status", Text, nullable=False, server_default="new"),
    _ts(name="created_at", nullable=False, server_default=func.now()),
    Column(
        "search_vector", TSVECTOR,
        Computed(
            "to_tsvector('english', "
            "coalesce(title,'') || ' ' || coalesce(clean_title,'') || ' ' || "
            "coalesce(summary,'') || ' ' || coalesce(full_text,''))",
            persisted=True,
        ),
    ),
    UniqueConstraint("feed_id", "guid", name="uq_articles_feed_guid"),
    CheckConstraint(
        "status IN ('new','scored','hidden','summarized')", name="status_valid"
    ),
)
Index("ix_articles_status", articles.c.status)
Index("ix_articles_score", articles.c.score.desc())
Index("ix_articles_feed_id", articles.c.feed_id)
Index("ix_articles_created_at", articles.c.created_at)
Index("ix_articles_search", articles.c.search_vector, postgresql_using="gin")
Index("ix_articles_topics", articles.c.topics, postgresql_using="gin")
Index("ix_articles_cluster_id", articles.c.cluster_id)


# Deterministic control on top of the soft LLM score: an adjustment nudges,
# `muted` hides outright.
topic_rules = Table(
    "topic_rules", metadata,
    Column("topic", Text, primary_key=True),
    Column("adjustment", Float, nullable=False, server_default="0"),
    Column("muted", Boolean, nullable=False, server_default="false"),
    _ts(name="created_at", nullable=False, server_default=func.now()),
)


# Per-user view state. Prunable with its article; the durable record of a vote
# lives in `votes`, which retention never touches.
user_article_state = Table(
    "user_article_state", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("article_id", Integer, ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
    _ts(name="read_at"),
    _ts(name="saved_at"),
    _ts(name="dismissed_at"),
    _ts(name="notified_at"),
    Column("opinion", Text),
    CheckConstraint("opinion IN ('liked','disliked')", name="opinion_valid"),
)
Index("ix_user_article_state_user_id", user_article_state.c.user_id)


# The training record for the preference profile. Deliberately decoupled from
# articles: the snapshots mean a vote survives its article being pruned, and
# article_id is a nullable convenience pointer rather than a data dependency.
# Per-device credentials for non-browser clients. Session cookies do not suit a
# native app: it cannot participate in the login redirect, and it needs a
# credential it can hold and the user can revoke for one device without signing
# out everywhere else.
api_tokens = Table(
    "api_tokens", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    # The token itself is never stored. It is a password: keep only the hash,
    # so a database leak does not hand over every reader's account.
    Column("token_hash", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    _ts(name="created_at", nullable=False, server_default=func.now()),
    _ts(name="last_used_at"),
    _ts(name="revoked_at"),
)

votes = Table(
    "votes", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("article_id", Integer, ForeignKey("articles.id", ondelete="SET NULL")),
    Column("value", Integer, nullable=False),
    Column("title_snapshot", Text),
    Column("summary_snapshot", Text),
    # Topics as they were when the vote was cast. On the vote and not read back
    # off the article for the same reason the title and summary are: retention
    # deletes articles, `article_id` goes NULL, and the vote outlives it. Topic
    # affinity is computed from these, so without the snapshot the reader's
    # learned preferences would quietly decay every time the pruner ran.
    Column("topics_snapshot", ARRAY(Text)),
    _ts(name="created_at", nullable=False, server_default=func.now()),
    CheckConstraint("value IN (1,-1)", name="value_valid"),
)
Index("ix_votes_article_id", votes.c.article_id)
Index("ix_votes_user_id", votes.c.user_id)


# Tombstones so retention-deleted articles are not re-ingested on the next poll.
# UNIQUE(feed_id, guid) on `articles` cannot do this: it lives on the row that
# was just deleted.
seen_guids = Table(
    "seen_guids", metadata,
    Column("feed_id", Integer, ForeignKey("feeds.id", ondelete="CASCADE"), primary_key=True),
    Column("guid", Text, primary_key=True),
    _ts(name="first_seen", nullable=False, server_default=func.now()),
)


# One per reader. It was a singleton, which meant one person's likes and
# dislikes shaped what everyone was shown -- and votes have been per-user since
# accounts arrived, so the profile derived from them had no business being
# shared.
preferences = Table(
    "preferences", metadata,
    # user_id is the key: one profile per reader, so a surrogate id would only
    # ever be a second way to say the same thing.
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"),
           primary_key=True),
    Column("profile_text", Text, nullable=False, server_default=""),
    _ts(name="updated_at", nullable=False, server_default=func.now()),
)


settings = Table(
    "settings", metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)


# One row per pipeline run. LOG_FORMAT=json already emits timings, but nothing
# surfaced them; this is what /insights reads.
pipeline_runs = Table(
    "pipeline_runs", metadata,
    Column("id", Integer, primary_key=True),
    _ts(name="started_at", nullable=False, server_default=func.now()),
    _ts(name="finished_at"),
    Column("scored_n", Integer, nullable=False, server_default="0"),
    Column("summarized_n", Integer, nullable=False, server_default="0"),
    Column("errors_n", Integer, nullable=False, server_default="0"),
    Column("llm_calls", Integer, nullable=False, server_default="0"),
    Column("skipped", Boolean, nullable=False, server_default="false"),
)
Index("ix_pipeline_runs_started_at", pipeline_runs.c.started_at.desc())


# Per-user topic stances. Scores are shared — there is one LLM pass per article
# — so these cannot re-score anything. They shape *this user's* list at read
# time instead: a boost lifts matching articles, a hide removes them, and
# neither is visible to anyone else.
user_topic_prefs = Table(
    "user_topic_prefs", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"),
           primary_key=True),
    Column("topic", Text, primary_key=True),
    Column("stance", Text, nullable=False),
    _ts(name="created_at", nullable=False, server_default=func.now()),
    CheckConstraint("stance IN ('more','hide')", name="stance_valid"),
)


# A bounded log of what was actually said to Ollama and what came back.
# Off by default: it is a row per LLM call, and prompts are large. On, it is the
# difference between "0 scored" and knowing the server answered 404.
ollama_calls = Table(
    "ollama_calls", metadata,
    Column("id", Integer, primary_key=True),
    _ts(name="at", nullable=False, server_default=func.now()),
    Column("action", Text),
    Column("model", Text),
    Column("endpoint", Text),
    Column("ok", Boolean, nullable=False, server_default="false"),
    Column("status_code", Integer),
    Column("duration_ms", Integer),
    Column("request_preview", Text),
    Column("response_preview", Text),
    Column("error", Text),
)
Index("ix_ollama_calls_at", ollama_calls.c.at.desc())


# One cached digest per user. Keyed by a fingerprint of the unread set, so a
# digest is reused until what you have not read actually changes — otherwise
# every page load would cost an Ollama call.
digests = Table(
    "digests", metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"),
           primary_key=True),
    Column("body", Text, nullable=False),
    Column("article_count", Integer, nullable=False, server_default="0"),
    Column("fingerprint", Text, nullable=False),
    _ts(name="created_at", nullable=False, server_default=func.now()),
)


login_attempts = Table(
    "login_attempts", metadata,
    Column("username", Text, primary_key=True),
    Column("failures", Integer, nullable=False, server_default="0"),
    _ts(name="last_failure_at"),
)
