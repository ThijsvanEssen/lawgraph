"""What the schema need not run again on a database that has it (``schema.ensure_schema``).

A column added to a table that has it, an option set on an index that has it: PostgreSQL takes
a lock every read waits for (ACCESS EXCLUSIVE) for either, also when it changes nothing. Beside
a long read the schema waited for it, and deadlocked with it (23 Nov: the sitemaps); left out,
a release without a new column starts beside any read.
"""

from __future__ import annotations

import re

import psycopg

# A column the schema adds to a table that may be older than it (a step 0 of a deploy).
ADDED = re.compile(
    r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)([^;]*);?", re.IGNORECASE
)
# An option the schema sets on an index that may have been made without it.
INDEX_OPTION = re.compile(r"ALTER INDEX (\w+) SET \((\w+) = (\w+)\);?")


def present_columns(conn: psycopg.Connection) -> list[tuple[str, str, bool, bool]]:
    """The columns of the tables of the database: table, column, whether it is generated,
    and whether it is required (NOT NULL without a default, not generated)."""
    return conn.execute(
        "SELECT table_name, column_name, is_generated = 'ALWAYS',"
        " is_nullable = 'NO' AND column_default IS NULL AND is_generated <> 'ALWAYS'"
        " FROM information_schema.columns WHERE table_schema = current_schema()"
    ).fetchall()


def index_options(conn: psycopg.Connection) -> set[str]:
    """The options of the indexes of the database, as ``index:option=value``."""
    rows = conn.execute(
        "SELECT c.relname || ':' || o FROM pg_class c CROSS JOIN unnest(c.reloptions) o"
        " WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind = 'i'"
    ).fetchall()
    return {row[0] for row in rows}


def needed(statement: str, columns: set[tuple[str, str]], options: set[str]) -> str:
    """*statement* without the columns of *columns* it adds and the options of *options*
    it sets."""
    statement = ADDED.sub(lambda m: "" if (m[1], m[2]) in columns else m[0], statement)
    return INDEX_OPTION.sub(
        lambda m: "" if f"{m[1]}:{m[2]}={m[3]}" in options else m[0], statement
    )
