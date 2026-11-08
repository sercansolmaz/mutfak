"""SQLite storage: schema, connections and the 30-day retention rule."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("DB_PATH", "/srv/data/mutfak.db")
RETENTION_DAYS = 30  # YouTube API policy: drop comment text and author names after 30 days

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id           TEXT PRIMARY KEY,          -- YouTube comment id
    video_id     TEXT NOT NULL,
    parent_id    TEXT,                      -- set for replies
    author       TEXT,                      -- NULL after 30 days
    text         TEXT,                      -- NULL after 30 days
    published_at TEXT NOT NULL,             -- ISO 8601, UTC
    analyzed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_comments_published ON comments(published_at);

-- Insight cards. kind: request | criticism | news
-- Only "request" topics go through approval and can appear on the public board.
CREATE TABLE IF NOT EXISTS topics (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_comments (
    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    comment_id TEXT NOT NULL REFERENCES comments(id),
    PRIMARY KEY (topic_id, comment_id)
);

-- Questions that seem to be waiting for an answer from the channel owner.
CREATE TABLE IF NOT EXISTS questions (
    comment_id TEXT PRIMARY KEY REFERENCES comments(id),
    summary    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open'       -- open | done
);

-- Public board votes: one per visitor cookie, max 20 per IP hash per topic.
CREATE TABLE IF NOT EXISTS votes (
    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    voter_id   TEXT NOT NULL,
    ip_hash    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (topic_id, voter_id)
);
CREATE INDEX IF NOT EXISTS idx_votes_ip ON votes(topic_id, ip_hash);

-- Nightly run log, shown in the private panel.
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    fetched     INTEGER NOT NULL DEFAULT 0,
    quota_units INTEGER NOT NULL DEFAULT 0,
    purged      INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'running',  -- running | ok | error
    message     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute(
        "INSERT INTO state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def purge_old(conn):
    """Remove text and author names of comments older than 30 days.
    Rows stay so topic counts survive and comments are not fetched again."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur = conn.execute(
        "UPDATE comments SET text = NULL, author = NULL "
        "WHERE published_at < ? AND (text IS NOT NULL OR author IS NOT NULL)",
        (cutoff,),
    )
    # Question summaries are derived from comment text, so they expire too.
    conn.execute(
        "DELETE FROM questions WHERE comment_id IN "
        "(SELECT id FROM comments WHERE published_at < ?)",
        (cutoff,),
    )
    return cur.rowcount
