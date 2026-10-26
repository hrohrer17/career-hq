"""Getting-started checklist, next best conversation, and turning a suggested connection into a contact."""

import json

from app import db


def _lead(conn, track="energy", answers=""):
    cur = conn.execute("INSERT INTO leads(kind, track, title, detail, created_at) VALUES ('connect', ?, ?, ?, ?)",
                       (track, "Project developer · Cascade Solar Development",
                        json.dumps({"role": "Project developer", "where": "Cascade Solar Development", "why": "Knows the work.",
                                    "answers_question": answers, "how_to_find": "Alumni directory",
                                    "search_phrase": "project developer solar", "opening": "Hi"}), db.now()))
    return cur.lastrowid


def test_getting_started_ticks_off_from_real_data(client):
    gs = {g["key"]: g["done"] for g in client.get("/api/dashboard").json()["getting_started"]}
    # Sample data: employers and contacts exist; no leads, no analyzed conversation, only seeded scores.
    assert gs == {"employers": True, "connections": False, "contact": True, "conversation": False, "score": True}
    with db.connect() as conn:
        _lead(conn)
    assert client.get("/api/dashboard").json()["getting_started"][1]["done"] is True


def test_next_conversation_prefers_someone_you_know(client):
    nc = client.get("/api/dashboard").json()["next_conversation"]
    # The first open question is tagged energy_dev; Priya (Cascade, an energy_dev employer) has no
    # conversation yet in the sample, so she's the one to ask.
    assert nc["type"] == "contact" and "Priya Raman" in nc["who"] and nc["href"].startswith("#/contact/")


def test_next_conversation_falls_back_to_a_matching_suggestion(client):
    with db.connect() as conn:
        conn.execute("UPDATE questions SET path = NULL")
        _lead(conn, answers="In project development, how much of the job is commercial deal-making")
    nc = client.get("/api/dashboard").json()["next_conversation"]
    assert nc["type"] == "lead" and nc["question"].startswith("In project development")


def test_found_someone_creates_a_contact_with_context(client):
    with db.connect() as conn:
        lid = _lead(conn, answers="How much is modeling?")
        cascade = db.one(conn, "SELECT id FROM employers WHERE name LIKE 'Cascade%'")["id"]
    r = client.post(f"/api/connections/{lid}/contact", json={"name": "Dana Ortiz", "role": "", "employer_id": cascade})
    cid = r.json()["contact_id"]
    profile = client.get(f"/api/contacts/{cid}").json()
    assert profile["name"] == "Dana Ortiz" and profile["role"] == "Project developer"
    assert profile["employer"] == "Cascade Solar Development" and profile["how_met"] == "Alumni directory (suggested by Connections)"
    assert "Could answer: How much is modeling?" in profile["notes"][0]["text"]
    assert client.post(f"/api/connections/{lid}/contact", json={"name": "Again"}).status_code == 409
    assert client.get("/api/connections").json()["connects"][0]["contact_id"] == cid


def test_short_role():
    from app.connections import short_role
    assert short_role("Project development manager who takes recreation projects from feasibility") == "Project development manager"
    assert short_role("Former MBA intern or recruiting lead, knows hiring") == "Former MBA intern or recruiting lead"
    assert short_role("Controls engineer") == "Controls engineer"
