"""Internship HQ: the user's 1-3 recruiting tracks, side by side, with employers and opportunities.

Tracks come from the tracks table (see tracks.py). Opportunities carry a cycle: the upcoming
internship, a possible second internship, or full-time. A second internship is kept separate
instead of being assumed.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from . import db, tracks as tracks_mod

STAGES = ["Researching", "Exploring", "Networking", "Applied", "Interviewing", "Offer"]
OPP_STATUSES = STAGES + ["Closed"]                 # Closed = rejected, declined or dropped
EMPLOYER_STAGES = STAGES + ["Not a fit"]
CYCLES = ["Upcoming internship", "Second internship (if any)", "Full-time"]


class InvalidInput(ValueError):
    pass


class NotFound(Exception):
    pass


def check_date(value: str) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise InvalidInput("Dates must be YYYY-MM-DD.") from exc


def check_track(conn: sqlite3.Connection, key: str) -> str:
    if key not in tracks_mod.track_keys(conn):
        raise InvalidInput(f"Unknown track: {key}.")
    return key


def check_choice(value: str, allowed: list[str] | dict, what: str) -> str:
    if value not in allowed:
        raise InvalidInput(f"Unknown {what}: {value}.")
    return value


def _opportunity_rows(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> list[dict]:
    return db.rows(conn, f"""SELECT o.*, e.name AS employer FROM opportunities o
                             LEFT JOIN employers e ON e.id = o.employer_id {where}""", params)


def _sort_opps(opps: list[dict]) -> list[dict]:
    rank = {s: i for i, s in enumerate(OPP_STATUSES)}
    # Closed last, then furthest stage first, then soonest due date.
    return sorted(opps, key=lambda o: (o["status"] == "Closed", -rank.get(o["status"], 0), o["due"] or "9999"))


def overview(conn: sqlite3.Connection) -> dict:
    tracks = []
    for t in tracks_mod.all_tracks(conn):
        key = t["key"]
        employers = db.rows(conn, """
            SELECT e.*, p.name AS path_name,
                   (SELECT COUNT(*) FROM contacts c WHERE c.employer_id = e.id) AS contacts,
                   (SELECT COUNT(*) FROM opportunities o WHERE o.employer_id = e.id AND o.status != 'Closed') AS open_opps,
                   (SELECT COUNT(*) FROM employer_notes n WHERE n.employer_id = e.id) AS notes
            FROM employers e LEFT JOIN paths p ON p.key = e.path
            WHERE e.track = ? ORDER BY e.name""", (key,))
        opps = _sort_opps(_opportunity_rows(conn, "WHERE o.track = ?", (key,)))
        tracks.append({"track": key, **t, "employers": employers, "opportunities": opps})
    return {"planning_note": db.setting(conn, "planning_note"), "tracks": tracks, "stages": STAGES,
            "opp_statuses": OPP_STATUSES, "employer_stages": EMPLOYER_STAGES, "cycles": CYCLES,
            "today": date.today().isoformat()}


def employer_page(conn: sqlite3.Connection, employer_id: int) -> dict | None:
    e = db.one(conn, """SELECT e.*, p.name AS path_name FROM employers e
                        LEFT JOIN paths p ON p.key = e.path WHERE e.id = ?""", (employer_id,))
    if e is None:
        return None
    t = db.one(conn, "SELECT name FROM tracks WHERE key = ?", (e["track"],))
    e["track_name"] = t["name"] if t else e["track"]
    e["profile"] = json.loads(e.get("profile") or "{}")
    e["opportunities"] = _sort_opps(_opportunity_rows(conn, "WHERE o.employer_id = ?", (employer_id,)))
    e["contacts"] = db.rows(conn, """SELECT c.id, c.name, c.role,
                                        (SELECT MAX(occurred_on) FROM conversations v WHERE v.contact_id = c.id) AS last_contacted
                                     FROM contacts c WHERE c.employer_id = ? ORDER BY c.name""", (employer_id,))
    e["notes"] = db.rows(conn, """SELECT n.id, n.text, n.created_at, v.occurred_on, c.id AS contact_id, c.name AS contact
                                  FROM employer_notes n
                                  LEFT JOIN conversations v ON v.id = n.conversation_id
                                  LEFT JOIN contacts c ON c.id = v.contact_id
                                  WHERE n.employer_id = ? ORDER BY n.id DESC""", (employer_id,))
    e["learnings"] = db.rows(conn, """SELECT l.text, l.created_at, c.id AS contact_id, c.name AS contact
                                      FROM learnings l LEFT JOIN conversations v ON v.id = l.conversation_id
                                      LEFT JOIN contacts c ON c.id = v.contact_id
                                      WHERE l.employer_id = ? ORDER BY l.id DESC""", (employer_id,))
    e["questions"] = db.rows(conn, """SELECT id, text, status, answer FROM questions
                                      WHERE employer_id = ? ORDER BY status DESC, id""", (employer_id,))
    return e


def create_employer(conn: sqlite3.Connection, data: dict) -> int:
    name = data["name"].strip()
    if db.one(conn, "SELECT 1 FROM employers WHERE lower(name) = lower(?)", (name,)):
        raise InvalidInput(f"{name} already exists.")
    check_track(conn, data["track"])
    check_choice(data.get("stage", "Researching"), EMPLOYER_STAGES, "stage")
    if data.get("path") and not db.one(conn, "SELECT 1 FROM paths WHERE key = ?", (data["path"],)):
        raise InvalidInput("Unknown career path.")
    cur = conn.execute("INSERT INTO employers(name, track, path, location, stage, summary) VALUES (?,?,?,?,?,?)",
                       (name, data["track"], data.get("path") or None, data.get("location", "").strip(),
                        data.get("stage", "Researching"), data.get("summary", "").strip()))
    return cur.lastrowid


def update_employer(conn: sqlite3.Connection, employer_id: int, changes: dict) -> None:
    if not db.one(conn, "SELECT 1 FROM employers WHERE id = ?", (employer_id,)):
        raise NotFound("Employer not found.")
    if "stage" in changes:
        check_choice(changes["stage"], EMPLOYER_STAGES, "stage")
    if "track" in changes:
        check_track(conn, changes["track"])
    if changes.get("path") and not db.one(conn, "SELECT 1 FROM paths WHERE key = ?", (changes["path"],)):
        raise InvalidInput("Unknown career path.")
    for col in ("stage", "track", "path", "location", "summary"):
        if col in changes:
            value = changes[col].strip() if isinstance(changes[col], str) else changes[col]
            conn.execute(f"UPDATE employers SET {col} = ? WHERE id = ?", (value or (None if col == 'path' else ''), employer_id))


def add_employer_note(conn: sqlite3.Connection, employer_id: int, text: str) -> int:
    if not db.one(conn, "SELECT 1 FROM employers WHERE id = ?", (employer_id,)):
        raise NotFound("Employer not found.")
    cur = conn.execute("INSERT INTO employer_notes(employer_id, text, created_at) VALUES (?,?,?)",
                       (employer_id, text.strip(), db.now()))
    return cur.lastrowid


def _check_opp(conn: sqlite3.Connection, data: dict) -> dict:
    out = {}
    if "employer_id" in data:
        eid = data["employer_id"]
        if eid is not None and not db.one(conn, "SELECT 1 FROM employers WHERE id = ?", (eid,)):
            raise InvalidInput("Unknown employer.")
        out["employer_id"] = eid
    if "track" in data:
        out["track"] = check_track(conn, data["track"])
    if "status" in data:
        out["status"] = check_choice(data["status"], OPP_STATUSES, "status")
    if "cycle" in data:
        out["cycle"] = check_choice(data["cycle"], CYCLES, "cycle")
    if "due" in data:
        out["due"] = check_date(data["due"] or "")
    for col in ("title", "next_action", "notes"):
        if col in data:
            out[col] = (data[col] or "").strip()
    if "title" in out and not out["title"]:
        raise InvalidInput("An opportunity needs a title.")
    return out


def create_opportunity(conn: sqlite3.Connection, data: dict) -> int:
    clean = _check_opp(conn, {"status": "Researching", "cycle": "Upcoming internship", "next_action": "", "due": "",
                              "notes": "", **data})
    if "track" not in clean:
        # Default to the employer's track, so an opportunity can't land in the other column by accident.
        emp = db.one(conn, "SELECT track FROM employers WHERE id = ?", (clean.get("employer_id"),))
        if emp is None:
            raise InvalidInput("Choose a track or an employer.")
        clean["track"] = emp["track"]
    clean["updated_at"] = db.now()
    cols = ", ".join(clean)
    cur = conn.execute(f"INSERT INTO opportunities({cols}) VALUES ({', '.join('?' for _ in clean)})",
                       tuple(clean.values()))
    return cur.lastrowid


def update_opportunity(conn: sqlite3.Connection, opp_id: int, data: dict) -> dict:
    if not db.one(conn, "SELECT 1 FROM opportunities WHERE id = ?", (opp_id,)):
        raise NotFound("Opportunity not found.")
    clean = _check_opp(conn, data)
    clean["updated_at"] = db.now()
    conn.execute(f"UPDATE opportunities SET {', '.join(f'{k} = ?' for k in clean)} WHERE id = ?",
                 (*clean.values(), opp_id))
    return db.one(conn, "SELECT * FROM opportunities WHERE id = ?", (opp_id,))


def complete_next_action(conn: sqlite3.Connection, opp_id: int, new_action: str = "", new_due: str = "") -> dict:
    """Mark the current next step done. The finished step is kept in the notes as a dated log line."""
    o = db.one(conn, "SELECT * FROM opportunities WHERE id = ?", (opp_id,))
    if o is None:
        raise NotFound("Opportunity not found.")
    if not o["next_action"]:
        raise InvalidInput("There is no next step to complete.")
    log = f"Done {date.today().isoformat()}: {o['next_action']}"
    notes = f"{o['notes']}\n{log}".strip()
    return update_opportunity(conn, opp_id, {"next_action": new_action, "due": new_due, "notes": notes})
