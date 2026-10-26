"""SQLite storage: the schema, the demo seed, and small query helpers.

Every record the AI can affect keeps a link back to the conversation it came from
(conversation_id), so any saved change can be traced to the notes that justified it.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paths (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tracks (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short TEXT NOT NULL,
    role TEXT NOT NULL,
    blurb TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS employers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    track TEXT NOT NULL REFERENCES tracks(key),
    path TEXT REFERENCES paths(key),
    location TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT 'Researching',
    summary TEXT NOT NULL DEFAULT '',
    profile TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    employer_id INTEGER REFERENCES employers(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    track TEXT NOT NULL REFERENCES tracks(key),
    status TEXT NOT NULL DEFAULT 'Researching',
    next_action TEXT NOT NULL DEFAULT '',
    due TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    cycle TEXT NOT NULL DEFAULT 'Upcoming internship',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    employer_id INTEGER REFERENCES employers(id) ON DELETE SET NULL,
    role TEXT NOT NULL DEFAULT '',
    how_met TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    occurred_on TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analysis_status TEXT NOT NULL DEFAULT 'not_analyzed',
    injection_flag TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    model TEXT NOT NULL,
    outcome TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    proposals_total INTEGER NOT NULL DEFAULT 0,
    blocked_by_validator INTEGER NOT NULL DEFAULT 0,
    blocked_reasons TEXT NOT NULL DEFAULT '[]',
    tools_used TEXT NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'debrief'
);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    evidence TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_at TEXT NOT NULL DEFAULT '',
    applied_ref TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    due TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    employer_id INTEGER REFERENCES employers(id) ON DELETE SET NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contact_notes (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employer_notes (
    id INTEGER PRIMARY KEY,
    employer_id INTEGER NOT NULL REFERENCES employers(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    path TEXT REFERENCES paths(key),
    employer_id INTEGER REFERENCES employers(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered')),
    answer TEXT NOT NULL DEFAULT '',
    created_conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    answered_conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    answered_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS criteria (
    key TEXT PRIMARY KEY,
    rank INTEGER NOT NULL,
    weight REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS employer_scores (
    employer_id INTEGER NOT NULL REFERENCES employers(id) ON DELETE CASCADE,
    criterion TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (employer_id, criterion)
);
CREATE TABLE IF NOT EXISTS employer_dealbreakers (
    employer_id INTEGER NOT NULL REFERENCES employers(id) ON DELETE CASCADE,
    dealbreaker TEXT NOT NULL,
    PRIMARY KEY (employer_id, dealbreaker)
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    track TEXT NOT NULL REFERENCES tracks(key),
    params TEXT NOT NULL,
    fit TEXT NOT NULL,
    risks TEXT NOT NULL DEFAULT '[]',
    why TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'Low',
    from_user INTEGER NOT NULL DEFAULT 0,
    reaction TEXT CHECK (reaction IN ('interested', 'maybe', 'no')),
    employer_id INTEGER REFERENCES employers(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS directions (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    detail TEXT NOT NULL,
    picked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('connect', 'multiplier')),
    track TEXT REFERENCES tracks(key) ON DELETE SET NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'added', 'dismissed')),
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    evidence TEXT NOT NULL,
    path TEXT REFERENCES paths(key),
    employer_id INTEGER REFERENCES employers(id) ON DELETE SET NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
"""

# Columns added after the first release. init_db adds any that an older database is missing,
# so a database created earlier (for example a private one) keeps working without a rebuild.
MIGRATIONS = [
    ("opportunities", "notes", "TEXT NOT NULL DEFAULT ''"),
    ("opportunities", "cycle", "TEXT NOT NULL DEFAULT 'Upcoming internship'"),
    ("opportunities", "updated_at", "TEXT NOT NULL DEFAULT ''"),
    ("employers", "profile", "TEXT NOT NULL DEFAULT '{}'"),   # parameters, e.g. hours, travel, pay
    ("runs", "kind", "TEXT NOT NULL DEFAULT 'debrief'"),       # debrief | scout | pathfinder | connections
    ("leads", "contact_id", "INTEGER REFERENCES contacts(id) ON DELETE SET NULL"),
]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """One connection per request: commit on success, roll back on error, always close."""
    db = _connect(config.DB_PATH)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def rows(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in db.execute(sql, params)]


def one(db: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    r = db.execute(sql, params).fetchone()
    return dict(r) if r else None


OLD_TRACK_CHECK = "CHECK (track IN ('outdoor', 'energy'))"


def _upgrade_fixed_tracks(path: Path) -> None:
    """Databases made before tracks were configurable hard-code two tracks in a CHECK constraint.

    SQLite can't drop a constraint, so rebuild those two tables without it (the documented
    create-copy-drop-rename procedure), with foreign keys off while the tables are swapped.
    """
    if not path.exists():
        return
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in ("employers", "opportunities"):
            row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
            if not row or OLD_TRACK_CHECK not in row[0]:
                continue
            new_sql = row[0].replace(OLD_TRACK_CHECK, "REFERENCES tracks(key)", 1)
            new_sql = new_sql.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}__new", 1)
            conn.execute(new_sql)
            conn.execute(f"INSERT INTO {table}__new SELECT * FROM {table}")
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {table}__new RENAME TO {table}")
        conn.commit()
    finally:
        conn.close()


def _backfill_tracks(db: sqlite3.Connection, seed: dict) -> None:
    """An upgraded database has employers on track keys but no rows in tracks: recreate them."""
    if db.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]:
        return
    used = [r[0] for r in db.execute("SELECT DISTINCT track FROM employers UNION SELECT DISTINCT track FROM opportunities")]
    known = {t["key"]: t for t in seed.get("tracks", [])}
    for pos, key in enumerate(sorted(used, key=lambda k: list(known).index(k) if k in known else 99), start=1):
        t = known.get(key, {"name": key.replace("-", " ").title(), "short": key[:14], "role": "Exploring", "blurb": ""})
        db.execute("INSERT INTO tracks(key, name, short, role, blurb, position) VALUES (?,?,?,?,?,?)",
                   (key, t["name"], t["short"], t["role"], t.get("blurb", ""), pos))


def init_db(with_sample: bool = False) -> None:
    """Create tables and upgrade older databases. The app starts blank: nothing is seeded unless
    asked (tests, evals, or the user's "Load sample data" button via load_sample)."""
    seed = json.loads(config.SAMPLE_SEED.read_text(encoding="utf-8"))
    _upgrade_fixed_tracks(config.DB_PATH)
    with connect() as db:
        db.executescript(SCHEMA)
        _backfill_tracks(db, seed)
        for table, column, ddl in MIGRATIONS:
            have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        # Cycle names used to be one student's ("Summer 2027"); they are generic now.
        db.execute("UPDATE opportunities SET cycle = 'Upcoming internship' WHERE cycle = 'Summer 2027'")
        db.execute("UPDATE opportunities SET cycle = 'Second internship (if any)' WHERE cycle LIKE 'Summer 2028%'")
        if with_sample and is_empty(db):
            load_seed(db, seed)


USER_TABLES = ["proposals", "candidates", "leads", "directions", "employer_scores", "employer_dealbreakers",
               "employer_notes", "contact_notes", "learnings", "tasks", "questions", "conversations",
               "opportunities", "contacts", "employers", "criteria", "tracks", "paths", "settings"]


def is_empty(db: sqlite3.Connection) -> bool:
    return all(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
               for t in ("tracks", "employers", "contacts", "settings"))


def load_sample(db: sqlite3.Connection) -> None:
    if not is_empty(db):
        raise ValueError("Sample data can only be loaded into an empty Career HQ. Start over first.")
    load_seed(db, json.loads(config.SAMPLE_SEED.read_text(encoding="utf-8")))


def reset_all(db: sqlite3.Connection) -> None:
    """Delete every record the user made. The AI run ledger is kept on purpose: it is what the daily
    budget is counted from, so starting over can't be used to reset spending."""
    for t in USER_TABLES:
        db.execute(f"DELETE FROM {t}")


def relative_date(value: str) -> str:
    """'+7' -> the date 7 days from today, '-14' -> 14 days ago; anything else is returned as is."""
    if value and value[0] in "+-" and value[1:].isdigit():
        return (date.today() + timedelta(days=int(value))).isoformat()
    return value


def load_seed(db: sqlite3.Connection, seed: dict) -> None:
    ts = now()
    for p in seed.get("paths", []):
        db.execute("INSERT OR IGNORE INTO paths(key, name) VALUES (?, ?)", (p["key"], p["name"]))
    for k, v in seed.get("settings", {}).items():
        db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, v))
    if "sample_notes" in seed:
        db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('sample_notes', ?)",
                   (json.dumps(seed["sample_notes"]),))

    for pos, t in enumerate(seed.get("tracks", []), start=1):
        db.execute("INSERT OR IGNORE INTO tracks(key, name, short, role, blurb, position) VALUES (?,?,?,?,?,?)",
                   (t["key"], t["name"], t["short"], t["role"], t.get("blurb", ""), pos))

    employer_ids: dict[str, int] = {}
    for e in seed.get("employers", []):
        cur = db.execute(
            "INSERT INTO employers(name, track, path, location, stage, summary) VALUES (?,?,?,?,?,?)",
            (e["name"], e["track"], e.get("path"), e.get("location", ""), e.get("stage", "Researching"),
             e.get("summary", "")))
        employer_ids[e["key"]] = cur.lastrowid
    for o in seed.get("opportunities", []):
        db.execute(
            """INSERT INTO opportunities(employer_id, title, track, status, next_action, due, notes, cycle, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (employer_ids.get(o.get("employer")), o["title"], o["track"], o.get("status", "Researching"),
             o.get("next_action", ""), relative_date(o.get("due", "")), o.get("notes", ""),
             o.get("cycle", "Upcoming internship"), ts))

    contact_ids: dict[str, int] = {}
    for c in seed.get("contacts", []):
        cur = db.execute(
            "INSERT INTO contacts(name, employer_id, role, how_met, email) VALUES (?,?,?,?,?)",
            (c["name"], employer_ids.get(c.get("employer")), c.get("role", ""), c.get("how_met", ""),
             c.get("email", "")))
        contact_ids[c["key"]] = cur.lastrowid
    for n in seed.get("contact_notes", []):
        db.execute("INSERT INTO contact_notes(contact_id, text, created_at) VALUES (?,?,?)",
                   (contact_ids[n["contact"]], n["text"], ts))
    for cv in seed.get("conversations", []):
        db.execute("INSERT INTO conversations(contact_id, occurred_on, notes, created_at) VALUES (?,?,?,?)",
                   (contact_ids[cv["contact"]], relative_date(cv["occurred_on"]), cv["notes"], ts))
    for q in seed.get("questions", []):
        db.execute("INSERT INTO questions(text, why, path, employer_id, created_at) VALUES (?,?,?,?,?)",
                   (q["text"], q.get("why", ""), q.get("path"), employer_ids.get(q.get("employer")), ts))
    if seed.get("profile"):
        db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('profile', ?)", (json.dumps(seed["profile"]),))
    pr = seed.get("priorities")
    if pr:
        for i, key in enumerate(pr["ranking"]):
            db.execute("INSERT OR REPLACE INTO criteria(key, rank, weight) VALUES (?,?,?)",
                       (key, i + 1, pr.get("weights", {}).get(key, [25, 20, 15, 12, 10, 8, 6, 4][i])))
        db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('dealbreakers', ?)",
                   (json.dumps(pr.get("dealbreakers", [])),))
    for sc in seed.get("scores", []):
        for key, val in sc["scores"].items():
            score, note = (val, "") if isinstance(val, int) else (val[0], val[1])
            db.execute("INSERT INTO employer_scores(employer_id, criterion, score, note, updated_at) VALUES (?,?,?,?,?)",
                       (employer_ids[sc["employer"]], key, score, note, ts))
        for d in sc.get("dealbreakers", []):
            db.execute("INSERT INTO employer_dealbreakers(employer_id, dealbreaker) VALUES (?,?)",
                       (employer_ids[sc["employer"]], d))
    for t in seed.get("tasks", []):
        db.execute("INSERT INTO tasks(description, due, contact_id, employer_id, created_at) VALUES (?,?,?,?,?)",
                   (t["description"], relative_date(t.get("due", "")), contact_ids.get(t.get("contact")),
                    employer_ids.get(t.get("employer")), ts))


def setting(db: sqlite3.Connection, key: str, default: str = "") -> str:
    r = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else default
