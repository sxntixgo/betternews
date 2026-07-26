"""Data access. All SQL touching articles lives here.

The point is not tidiness. Article rows are shared between users while read
state is not, so *every* article query must be scoped by user_id. Scattered
raw SQL makes that a rule you remember; a repository makes it a rule the
signature enforces — miss it and the call doesn't compile.
"""

from app.repo import articles, users  # noqa: F401
