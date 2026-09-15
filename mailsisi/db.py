"""SQLite bookkeeping: which emails we've read, which conversation they belong
to, and which version of a file is the current one."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id       TEXT PRIMARY KEY,
    root_message_id TEXT,
    subject_norm    TEXT,
    distributor     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    last_seen       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    uid          TEXT PRIMARY KEY,
    message_id   TEXT,
    thread_id    TEXT,
    sender       TEXT,
    subject      TEXT,
    email_date   TEXT,
    distributor  TEXT,
    responded    INTEGER DEFAULT 0,
    processed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attachments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    message_uid       TEXT,
    thread_id         TEXT,
    distributor       TEXT,
    logical_name      TEXT,
    original_filename TEXT,
    saved_path        TEXT,
    content_hash      TEXT,
    size              INTEGER,
    seq               INTEGER,
    version           INTEGER DEFAULT 1,
    superseded        INTEGER DEFAULT 0,
    superseded_by     INTEGER,
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_att_hash           ON attachments(content_hash);
CREATE INDEX IF NOT EXISTS idx_att_thread_logical ON attachments(thread_id, logical_name, superseded);
CREATE INDEX IF NOT EXISTS idx_msg_message_id     ON messages(message_id);
"""

def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

# --- messages ---

def message_seen(conn: sqlite3.Connection, uid: str) -> bool:
    return conn.execute("SELECT 1 FROM messages WHERE uid = ?", (uid,)).fetchone() is not None

def insert_message(conn, uid, message_id, thread_id, sender, subject, email_date,
                   distributor, responded=0) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO messages
           (uid, message_id, thread_id, sender, subject, email_date, distributor, responded)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, message_id, thread_id, sender, subject, email_date, distributor, responded),
    )
    conn.commit()

def mark_responded(conn, uid) -> None:
    conn.execute("UPDATE messages SET responded = 1 WHERE uid = ?", (uid,))
    conn.commit()

def count_messages(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

def prune_old_messages(conn, keep: int) -> int:
    """Keep the db from growing forever: throw away the oldest rows for mail we
    skipped, keeping the newest `keep`. Distributor rows and every attachment row
    stay put, so nothing we downloaded is ever at risk. Skipped mail has no
    attachments or threads hanging off it, so this leaves no orphans - worst case
    a recent one gets looked at again and downloads nothing. Returns rows deleted."""
    cur = conn.execute(
        """DELETE FROM messages
           WHERE distributor IS NULL AND uid IN (
               SELECT uid FROM messages WHERE distributor IS NULL
               ORDER BY rowid DESC LIMIT -1 OFFSET ?
           )""",
        (keep,),
    )
    conn.commit()
    deleted = cur.rowcount
    if deleted:
        conn.execute("VACUUM")
    return deleted

def thread_for_message(conn, message_id: str) -> str | None:
    """Which conversation an already-seen Message-ID sits in."""
    if not message_id:
        return None
    row = conn.execute(
        "SELECT thread_id FROM messages WHERE message_id = ? AND thread_id IS NOT NULL LIMIT 1",
        (message_id,),
    ).fetchone()
    if row:
        return row["thread_id"]
    row = conn.execute(
        "SELECT thread_id FROM threads WHERE root_message_id = ? LIMIT 1", (message_id,)
    ).fetchone()
    return row["thread_id"] if row else None

# --- threads ---

def save_thread(conn, thread_id, root_message_id, subject_norm, distributor) -> None:
    conn.execute(
        """INSERT INTO threads (thread_id, root_message_id, subject_norm, distributor)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(thread_id) DO UPDATE SET last_seen = datetime('now')""",
        (thread_id, root_message_id, subject_norm, distributor),
    )
    conn.commit()

def touch_thread(conn, thread_id) -> None:
    conn.execute("UPDATE threads SET last_seen = datetime('now') WHERE thread_id = ?", (thread_id,))
    conn.commit()

# --- attachments ---

def attachment_with_hash(conn, content_hash: str):
    """Same bytes somewhere already? Then we've got this file."""
    return conn.execute(
        "SELECT * FROM attachments WHERE content_hash = ? LIMIT 1", (content_hash,)
    ).fetchone()

def current_version(conn, thread_id: str, logical_name: str):
    """The live, not-yet-replaced copy of this file in this conversation."""
    return conn.execute(
        """SELECT * FROM attachments
           WHERE thread_id = ? AND logical_name = ? AND superseded = 0
           ORDER BY version DESC LIMIT 1""",
        (thread_id, logical_name),
    ).fetchone()

def add_attachment(conn, message_uid, thread_id, distributor, logical_name,
                   original_filename, saved_path, content_hash, size, seq, version) -> int:
    cur = conn.execute(
        """INSERT INTO attachments
           (message_uid, thread_id, distributor, logical_name, original_filename,
            saved_path, content_hash, size, seq, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (message_uid, thread_id, distributor, logical_name, original_filename,
         saved_path, content_hash, size, seq, version),
    )
    conn.commit()
    return cur.lastrowid

def mark_replaced(conn, old_id: int, new_id: int) -> None:
    conn.execute(
        "UPDATE attachments SET superseded = 1, superseded_by = ? WHERE id = ?",
        (new_id, old_id),
    )
    conn.commit()
