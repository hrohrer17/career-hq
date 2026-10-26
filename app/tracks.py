"""Recruiting tracks: the 1 to 3 career directions a user is comparing, set up on first run.

Each track is a column in Internship HQ and a pipeline on the Dashboard. Employers and
opportunities belong to one track. Tracks are stored in the database (not hard-coded), so a new
user picks their own (the sample data has two: outdoor, energy).
"""

from __future__ import annotations

import re
import sqlite3

from . import db

MIN_TRACKS, MAX_TRACKS = 1, 3
ROLES = ["Primary focus", "Strong alternative", "Exploring"]

# Multiple-choice options for setup. "Something else" lets the user name their own.
PRESETS = [
    {"name": "Energy & infrastructure", "short": "Energy", "blurb": "Project development, commercial strategy and execution."},
    {"name": "Outdoor recreation", "short": "Outdoor", "blurb": "Recreation infrastructure, resorts and destinations, advocacy and industry."},
    {"name": "Real estate & development", "short": "Real estate", "blurb": "Acquisitions, development and asset management."},
    {"name": "Consulting", "short": "Consulting", "blurb": "Strategy and management consulting."},
    {"name": "Technology", "short": "Tech", "blurb": "Product, strategy and operations at technology companies."},
    {"name": "Finance / PE / VC", "short": "Finance", "blurb": "Investing, banking and private markets."},
    {"name": "Healthcare", "short": "Healthcare", "blurb": "Providers, payers, life sciences and health tech."},
    {"name": "Climate & sustainability", "short": "Climate", "blurb": "Decarbonization, climate tech and sustainability roles."},
    {"name": "Public sector & policy", "short": "Policy", "blurb": "Government, policy and public agencies."},
    {"name": "Nonprofit & social impact", "short": "Impact", "blurb": "Mission-driven organizations and social enterprises."},
    {"name": "Consumer & retail", "short": "Consumer", "blurb": "Brands, retail and consumer products."},
    {"name": "Manufacturing & industrials", "short": "Industrials", "blurb": "Operations, supply chain and industrial companies."},
]


class TrackError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def all_tracks(conn: sqlite3.Connection) -> list[dict]:
    return db.rows(conn, "SELECT key, name, short, role, blurb, position FROM tracks ORDER BY position")


def track_keys(conn: sqlite3.Connection) -> set[str]:
    return {r["key"] for r in db.rows(conn, "SELECT key FROM tracks")}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:30] or "track"


def _short(name: str) -> str:
    preset = next((p for p in PRESETS if p["name"].lower() == name.lower()), None)
    if preset:
        return preset["short"]
    first = re.split(r"[\s/&,]+", name.strip())[0]
    return first[:14] or name[:14]


def save(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    """Replace the user's tracks with this list (1-3 items), in order.

    Items that carry an existing key are renamed in place, so their employers and opportunities
    stay attached. A track left out of the list is removed, but only if nothing uses it.
    """
    if not MIN_TRACKS <= len(items) <= MAX_TRACKS:
        raise TrackError(f"Set up between {MIN_TRACKS} and {MAX_TRACKS} tracks.")
    cleaned = []
    for i, item in enumerate(items):
        name = re.sub(r"\s+", " ", str(item.get("name") or "")).strip()
        if not name:
            raise TrackError(f"Track {i + 1} needs a name.")
        if len(name) > 60:
            raise TrackError(f"Track {i + 1}'s name is too long (60 characters max).")
        role = item.get("role") or ""
        if len(items) == 1:
            role = "Primary focus"
        if role not in ROLES:
            raise TrackError(f"Choose a role for {name}.")
        blurb = str(item.get("blurb") or "").strip()[:200]
        if not blurb:
            blurb = next((p["blurb"] for p in PRESETS if p["name"].lower() == name.lower()), "")
        cleaned.append({"key": item.get("key"), "name": name, "role": role, "blurb": blurb,
                        "short": str(item.get("short") or "").strip()[:14] or _short(name)})

    names = [c["name"].lower() for c in cleaned]
    if len(set(names)) != len(names):
        raise TrackError("Each track needs a different name.")
    if sum(c["role"] == "Primary focus" for c in cleaned) != 1:
        raise TrackError("Mark exactly one track as your primary focus.")

    existing = {t["key"]: t for t in all_tracks(conn)}
    for c in cleaned:
        if c["key"] is not None and c["key"] not in existing:
            raise TrackError("Unknown track.", 404)
    kept = {c["key"] for c in cleaned if c["key"]}
    for key in set(existing) - kept:
        used = conn.execute("SELECT (SELECT COUNT(*) FROM employers WHERE track = ?) + "
                            "(SELECT COUNT(*) FROM opportunities WHERE track = ?)", (key, key)).fetchone()[0]
        if used:
            things = "1 employer or opportunity" if used == 1 else f"{used} employers and opportunities"
            raise TrackError(f"{existing[key]['name']} still has {things}. "
                             "Move them to another track before removing it.", 409)

    for key in set(existing) - kept:
        # Its mirrored career path goes too, unless a learning or question still points at it.
        try:
            conn.execute("DELETE FROM paths WHERE key = ?", (key,))
        except sqlite3.IntegrityError:
            pass
    # Positions are reassigned below; park existing rows on high numbers first to avoid clashes.
    conn.execute("UPDATE tracks SET position = position + 100")
    for key in set(existing) - kept:
        conn.execute("DELETE FROM tracks WHERE key = ?", (key,))
    taken = set(kept)
    for pos, c in enumerate(cleaned, start=1):
        if c["key"]:
            conn.execute("UPDATE tracks SET name = ?, short = ?, role = ?, blurb = ?, position = ? WHERE key = ?",
                         (c["name"], c["short"], c["role"], c["blurb"], pos, c["key"]))
        else:
            key, n = _slug(c["name"]), 2
            while key in taken or key in existing:
                key, n = f"{_slug(c['name'])}-{n}", n + 1
            taken.add(key)
            conn.execute("INSERT INTO tracks(key, name, short, role, blurb, position) VALUES (?,?,?,?,?,?)",
                         (key, c["name"], c["short"], c["role"], c["blurb"], pos))
    # A new user's career paths are their tracks (the sample user has finer-grained paths of its
    # own). Mirroring them gives learnings and questions something to be tagged with.
    for t in all_tracks(conn):
        conn.execute("INSERT INTO paths(key, name) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET name = excluded.name",
                     (t["key"], t["name"]))
    return all_tracks(conn)
