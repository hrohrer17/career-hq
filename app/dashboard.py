"""Data for the Dashboard: priorities, what's due, networking follow-ups, and pipeline progress.

Every number here supports a decision: what to do this week, who to follow up with, and how far
each recruiting track has got. No vanity counts.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from . import db, tracks as tracks_mod
from .internships import STAGES
HORIZON_DAYS = 14


def _bucket(due: str, today: date) -> str:
    if not due:
        return "undated"
    d = date.fromisoformat(due)
    if d < today:
        return "overdue"
    if d <= today + timedelta(days=7):
        return "this_week"
    if d <= today + timedelta(days=HORIZON_DAYS):
        return "next_week"
    return "later"


def build(conn: sqlite3.Connection, today: date | None = None) -> dict:
    today = today or date.today()

    priorities = {k: db.setting(conn, k) for k in ("current_priority", "planning_note", "north_star")}

    # Upcoming actions: dated tasks not tied to a person, plus each opportunity's next step.
    actions = []
    for t in db.rows(conn, """SELECT t.id, t.description, t.due, e.name AS employer, e.track
                              FROM tasks t LEFT JOIN employers e ON e.id = t.employer_id
                              WHERE t.status = 'open' AND t.contact_id IS NULL AND t.due != ''"""):
        actions.append({"type": "task", "id": t["id"], "text": t["description"], "due": t["due"],
                        "context": t["employer"] or "", "track": t["track"]})
    for o in db.rows(conn, """SELECT o.id, o.title, o.next_action, o.due, o.track, o.employer_id, e.name AS employer
                              FROM opportunities o LEFT JOIN employers e ON e.id = o.employer_id
                              WHERE o.next_action != '' AND o.due != '' AND o.status NOT IN ('Offer', 'Closed')"""):
        actions.append({"type": "opportunity", "id": o["id"], "text": o["next_action"], "due": o["due"],
                        "context": " · ".join(x for x in (o["employer"], o["title"]) if x), "track": o["track"],
                        "employer_id": o["employer_id"]})
    for a in actions:
        a["bucket"] = _bucket(a["due"], today)
    upcoming = sorted((a for a in actions if a["bucket"] in ("overdue", "this_week", "next_week")),
                      key=lambda a: a["due"])
    later_count = sum(1 for a in actions if a["bucket"] == "later")

    # Networking follow-ups: suggestions waiting for review, then open tasks tied to a person.
    reviews = db.rows(conn, """SELECT c.id AS contact_id, c.name, v.id AS conversation_id, v.occurred_on,
                                      COUNT(p.id) AS pending
                               FROM proposals p JOIN conversations v ON v.id = p.conversation_id
                               JOIN contacts c ON c.id = v.contact_id
                               WHERE p.status = 'pending'
                               GROUP BY v.id ORDER BY v.occurred_on DESC""")
    followups = db.rows(conn, """SELECT t.id, t.description, t.due, c.id AS contact_id, c.name, e.name AS employer
                                 FROM tasks t JOIN contacts c ON c.id = t.contact_id
                                 LEFT JOIN employers e ON e.id = c.employer_id
                                 WHERE t.status = 'open'
                                 ORDER BY t.due = '', t.due, t.id""")
    for f in followups:
        f["bucket"] = _bucket(f["due"], today)

    # Pipeline: per track, how many opportunities sit at each stage, and the list itself.
    pipeline = []
    # This recruiting cycle (upcoming internship or full-time), nothing closed. A possible second
    # internship lives in Internship HQ only.
    for meta in tracks_mod.all_tracks(conn):
        key, name = meta["key"], meta["name"]
        opps = db.rows(conn, """SELECT o.id, o.title, o.status, o.next_action, o.due, o.employer_id, e.name AS employer
                                FROM opportunities o LEFT JOIN employers e ON e.id = o.employer_id
                                WHERE o.track = ? AND o.cycle != 'Second internship (if any)' AND o.status != 'Closed'""", (key,))
        rank = {s: i for i, s in enumerate(STAGES)}
        opps.sort(key=lambda o: (-rank.get(o["status"], -1), o["due"] or "9999"))
        counts = {s: sum(1 for o in opps if o["status"] == s) for s in STAGES}
        furthest = next((s for s in reversed(STAGES) if counts[s]), None)
        pipeline.append({"track": key, "name": name, "role": meta["role"], "total": len(opps), "counts": counts,
                         "furthest_stage": furthest, "opportunities": opps})

    questions = db.rows(conn, "SELECT id, text, status, path FROM questions ORDER BY id")
    open_q = [q for q in questions if q["status"] == "open"]

    return {"today": today.isoformat(), "priorities": priorities, "stages": STAGES,
            "getting_started": getting_started(conn), "next_conversation": next_conversation(conn, open_q),
            "upcoming": upcoming, "later_count": later_count,
            "reviews": reviews, "followups": followups, "pipeline": pipeline,
            "learning": {"answered": len(questions) - len(open_q), "total": len(questions),
                         "next_question": open_q[0]["text"] if open_q else ""}}


def getting_started(conn: sqlite3.Connection) -> list[dict]:
    """A new user's first steps, each ticked off by what's actually in the database."""
    def count(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]
    return [
        {"key": "employers", "label": "Find employers worth targeting", "href": "#/targets",
         "done": count("SELECT COUNT(*) FROM employers") > 0},
        {"key": "connections", "label": "See who to talk to and what multiplies your effort", "href": "#/connections",
         "done": count("SELECT COUNT(*) FROM leads") > 0},
        {"key": "contact", "label": "Add the first person you'll talk to", "href": "#/network",
         "done": count("SELECT COUNT(*) FROM contacts") > 0},
        {"key": "conversation", "label": "Log a conversation and let the AI pull out what you learned", "href": "#/network",
         "done": count("SELECT COUNT(*) FROM conversations WHERE analysis_status = 'analyzed'") > 0},
        {"key": "score", "label": "Score an employer on your priorities", "href": "#/decisions",
         "done": count("SELECT COUNT(*) FROM employer_scores WHERE note NOT LIKE 'AI estimate%'") > 0},
    ]


def next_conversation(conn: sqlite3.Connection, open_q: list[dict]) -> dict | None:
    """The most useful next conversation: an open question, and who could answer it.

    Prefers a person the user already has (at an employer on that question's track, not yet talked
    to), then a Connections suggestion written for that question, then any suggestion on its track.
    Plain matching, no AI call.
    """
    if not open_q:
        return None
    leads = db.rows(conn, "SELECT id, track, title, detail, status, contact_id FROM leads "
                          "WHERE kind = 'connect' AND status != 'dismissed' ORDER BY id")
    for q in open_q:
        contact = db.one(conn, """SELECT c.id, c.name, c.role, e.name AS employer FROM contacts c
                                  JOIN employers e ON e.id = c.employer_id
                                  WHERE (e.track = ? OR e.path = ?)
                                    AND NOT EXISTS (SELECT 1 FROM conversations v WHERE v.contact_id = c.id)
                                  ORDER BY c.id LIMIT 1""", (q["path"], q["path"])) if q["path"] else None
        if contact:
            return {"question": q["text"], "type": "contact", "who": f"{contact['name']} ({contact['role']}, {contact['employer']})",
                    "href": f"#/contact/{contact['id']}", "cta": "Log the conversation"}
        for lead in leads:
            d = json.loads(lead["detail"])
            if d.get("answers_question") and d["answers_question"].strip().lower()[:60] in q["text"].lower():
                return {"question": q["text"], "type": "lead", "who": lead["title"], "href": "#/connections",
                        "cta": "See how to find them"}
    q = open_q[0]
    lead = next((l for l in leads if l["track"] == q["path"]), leads[0] if leads else None)
    if lead:
        return {"question": q["text"], "type": "lead", "who": lead["title"], "href": "#/connections", "cta": "See how to find them"}
    return {"question": q["text"], "type": "none", "who": "", "href": "#/connections", "cta": "Find someone who could answer it"}
