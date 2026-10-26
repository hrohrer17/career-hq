"""Priorities, deal-breakers and the Decision Studio's weighted employer comparison.

Transparent on purpose: the user ranks eight criteria in setup, the rank sets default weights
(adjustable later), the user scores each employer 1-5 per criterion, and the match is a plain
weighted average. No AI judgment goes into the number. Missing scores are shown as unknowns,
not guessed: the highest-weight unscored criterion is the employer's "biggest unknown", the thing
most worth asking about in the next networking conversation.
"""

from __future__ import annotations

import json
import sqlite3

from . import db

CRITERIA = [
    {"key": "work", "name": "Enjoyable work & ownership", "hint": "Would you enjoy the day-to-day work and own real projects?"},
    {"key": "pay", "name": "Compensation & upside", "hint": "Base pay, bonus, equity or profit sharing."},
    {"key": "lifestyle", "name": "Location & lifestyle", "hint": "Where you'd live, the hours, and time for life outside work."},
    {"key": "impact", "name": "Mission & impact", "hint": "Environmental, public or social benefit of the work."},
    {"key": "team", "name": "Team & mentorship", "hint": "Strong colleagues and people who would teach you."},
    {"key": "growth", "name": "Learning & growth", "hint": "How fast you'd build skills and responsibility."},
    {"key": "stability", "name": "Stability", "hint": "Financial health and job security."},
    {"key": "brand", "name": "Brand & exit options", "hint": "How the name helps your next move."},
]
CRITERIA_KEYS = [c["key"] for c in CRITERIA]
RANK_WEIGHTS = [25, 20, 15, 12, 10, 8, 6, 4]   # 1st ... 8th; sums to 100

DEALBREAKERS = [
    {"key": "over_60_hours", "name": "Over 60-hour weeks"},
    {"key": "fully_in_office", "name": "Fully in-office"},
    {"key": "big_city_only", "name": "Big-city only"},
    {"key": "heavy_travel", "name": "Heavy travel"},
    {"key": "quota_roles", "name": "Commission or quota roles"},
    {"key": "fossil_fuels", "name": "Fossil fuels"},
    {"key": "defense", "name": "Defense"},
    {"key": "abroad", "name": "Relocating abroad"},
]
DEALBREAKER_KEYS = [d["key"] for d in DEALBREAKERS]


class DecisionError(ValueError):
    pass


# ---------- priorities ----------

def has_priorities(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM criteria").fetchone()[0] == len(CRITERIA)


def criteria(conn: sqlite3.Connection) -> list[dict]:
    """All eight criteria with the user's rank and weight, most important first."""
    saved = {r["key"]: r for r in db.rows(conn, "SELECT key, rank, weight FROM criteria")}
    out = [{**c, "rank": saved.get(c["key"], {}).get("rank"), "weight": saved.get(c["key"], {}).get("weight")}
           for c in CRITERIA]
    total = sum(c["weight"] or 0 for c in out) or 1
    for c in out:
        c["share"] = round(100 * (c["weight"] or 0) / total, 1)
    return sorted(out, key=lambda c: (c["rank"] is None, c["rank"] or 0))


def selected_dealbreakers(conn: sqlite3.Connection) -> list[str]:
    return json.loads(db.setting(conn, "dealbreakers", "[]"))


def save_priorities(conn: sqlite3.Connection, ranking: list[str], dealbreakers: list[str]) -> None:
    if sorted(ranking) != sorted(CRITERIA_KEYS):
        raise DecisionError("Rank all eight priorities, each once.")
    unknown = set(dealbreakers) - set(DEALBREAKER_KEYS)
    if unknown:
        raise DecisionError(f"Unknown deal-breaker: {', '.join(sorted(unknown))}.")
    conn.execute("DELETE FROM criteria")
    for i, key in enumerate(ranking):
        conn.execute("INSERT INTO criteria(key, rank, weight) VALUES (?,?,?)", (key, i + 1, RANK_WEIGHTS[i]))
    keep = [d for d in DEALBREAKER_KEYS if d in dealbreakers]
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('dealbreakers', ?)", (json.dumps(keep),))
    # An employer can only "hit" a deal-breaker the user still has.
    if keep:
        conn.execute(f"DELETE FROM employer_dealbreakers WHERE dealbreaker NOT IN ({','.join('?' * len(keep))})", keep)
    else:
        conn.execute("DELETE FROM employer_dealbreakers")


def set_weight(conn: sqlite3.Connection, key: str, weight: float) -> None:
    if key not in CRITERIA_KEYS:
        raise DecisionError("Unknown priority.")
    if not 0 <= weight <= 100:
        raise DecisionError("Weights run from 0 to 100.")
    if conn.execute("UPDATE criteria SET weight = ? WHERE key = ?", (weight, key)).rowcount != 1:
        raise DecisionError("Rank your priorities in setup first.")


def reset_weights(conn: sqlite3.Connection) -> None:
    for r in db.rows(conn, "SELECT key, rank FROM criteria"):
        conn.execute("UPDATE criteria SET weight = ? WHERE key = ?", (RANK_WEIGHTS[r["rank"] - 1], r["key"]))


# ---------- employer scores ----------

def set_score(conn: sqlite3.Connection, employer_id: int, key: str, score: int | None, note: str = "") -> None:
    if key not in CRITERIA_KEYS:
        raise DecisionError("Unknown priority.")
    if not db.one(conn, "SELECT 1 FROM employers WHERE id = ?", (employer_id,)):
        raise DecisionError("Unknown employer.")
    if score is None:
        conn.execute("DELETE FROM employer_scores WHERE employer_id = ? AND criterion = ?", (employer_id, key))
        return
    if score not in (1, 2, 3, 4, 5):
        raise DecisionError("Scores run from 1 to 5.")
    conn.execute("""INSERT INTO employer_scores(employer_id, criterion, score, note, updated_at) VALUES (?,?,?,?,?)
                    ON CONFLICT(employer_id, criterion) DO UPDATE SET score = excluded.score,
                    note = excluded.note, updated_at = excluded.updated_at""",
                 (employer_id, key, score, note.strip()[:300], db.now()))


def set_employer_dealbreakers(conn: sqlite3.Connection, employer_id: int, keys: list[str]) -> None:
    if not db.one(conn, "SELECT 1 FROM employers WHERE id = ?", (employer_id,)):
        raise DecisionError("Unknown employer.")
    allowed = set(selected_dealbreakers(conn))
    if set(keys) - allowed:
        raise DecisionError("That isn't one of your deal-breakers.")
    conn.execute("DELETE FROM employer_dealbreakers WHERE employer_id = ?", (employer_id,))
    for k in keys:
        conn.execute("INSERT INTO employer_dealbreakers(employer_id, dealbreaker) VALUES (?,?)", (employer_id, k))


def match(scores: dict[str, int], weights: dict[str, float]) -> dict:
    """Weighted match on a 0-100 scale, over the criteria that have a score.

    1 = 0, 3 = 50, 5 = 100. Coverage is the share of total weight that has been scored, so a high
    match built on one scored criterion reads as what it is.
    """
    total = sum(weights.values())
    scored_w = sum(w for k, w in weights.items() if k in scores)
    if not scores or scored_w == 0:
        return {"score": None, "coverage": 0}
    avg = sum(weights[k] * s for k, s in scores.items() if k in weights) / scored_w
    return {"score": round((avg - 1) / 4 * 100), "coverage": round(100 * scored_w / total) if total else 0}


def studio(conn: sqlite3.Connection) -> dict:
    crit = criteria(conn)
    weights = {c["key"]: c["weight"] or 0 for c in crit}
    names = {c["key"]: c["name"] for c in crit}
    db_names = {d["key"]: d["name"] for d in DEALBREAKERS}
    scores: dict[int, dict] = {}
    for r in db.rows(conn, "SELECT employer_id, criterion, score, note FROM employer_scores"):
        scores.setdefault(r["employer_id"], {})[r["criterion"]] = {"score": r["score"], "note": r["note"]}
    hits: dict[int, list[str]] = {}
    for r in db.rows(conn, "SELECT employer_id, dealbreaker FROM employer_dealbreakers"):
        hits.setdefault(r["employer_id"], []).append(r["dealbreaker"])

    ranked, ruled_out, unscored = [], [], []
    for e in db.rows(conn, """SELECT e.id, e.name, e.track, e.stage, e.location, t.position AS track_position
                              FROM employers e JOIN tracks t ON t.key = e.track ORDER BY e.name"""):
        s = scores.get(e["id"], {})
        m = match({k: v["score"] for k, v in s.items()}, weights)
        unknown = next((c for c in crit if c["key"] not in s and (c["weight"] or 0) > 0), None)
        row = {**e, **m, "scores": s, "scored": len(s),
               "ai_estimated": sum(1 for v in s.values() if (v["note"] or "").startswith("AI estimate")),
               "biggest_unknown": {"key": unknown["key"], "name": unknown["name"]} if unknown else None,
               "dealbreakers_hit": [{"key": k, "name": db_names.get(k, k)} for k in hits.get(e["id"], [])]}
        if row["dealbreakers_hit"]:
            ruled_out.append(row)
        elif m["score"] is None:
            unscored.append(row)
        else:
            ranked.append(row)
    ranked.sort(key=lambda r: (-r["score"], -r["coverage"], r["name"]))
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return {"criteria": crit, "criteria_names": names, "dealbreakers": selected_dealbreakers(conn),
            "dealbreaker_options": DEALBREAKERS, "ranked": ranked, "unscored": unscored, "ruled_out": ruled_out}
