"""Internship HQ: two tracks, opportunity edits, completing next steps, the second-summer cycle."""

import sqlite3

from app import config, db, internships


def _ids(conn):
    granite = db.one(conn, "SELECT id FROM employers WHERE name LIKE 'Granite%'")["id"]
    cascade_opp = db.one(conn, "SELECT id FROM opportunities WHERE title = 'Project Development MBA Intern'")["id"]
    return granite, cascade_opp


def test_overview_has_two_tracks_and_keeps_second_summer_separate(client):
    d = client.get("/api/internships").json()
    assert [t["track"] for t in d["tracks"]] == ["outdoor", "energy"]
    assert d["tracks"][0]["role"] == "Primary focus"
    outdoor = d["tracks"][0]["opportunities"]
    assert any(o["cycle"] == "Second internship (if any)" for o in outdoor)
    # The Dashboard's pipeline must not count the second-internship option.
    dash = client.get("/api/dashboard").json()
    assert next(p for p in dash["pipeline"] if p["track"] == "outdoor")["total"] == 3


def test_status_change_and_validation(client):
    with db.connect() as conn:
        _, opp = _ids(conn)
    assert client.patch(f"/api/opportunities/{opp}", json={"status": "Interviewing"}).json()["status"] == "Interviewing"
    assert client.patch(f"/api/opportunities/{opp}", json={"status": "Hired!!"}).status_code == 422
    assert client.patch(f"/api/opportunities/{opp}", json={"due": "next Friday"}).status_code == 422
    assert client.patch(f"/api/opportunities/{opp}", json={"cycle": "Summer 2030"}).status_code == 422
    assert client.patch("/api/opportunities/9999", json={"status": "Applied"}).status_code == 404


def test_closed_drops_out_of_dashboard(client):
    with db.connect() as conn:
        _, opp = _ids(conn)
    client.patch(f"/api/opportunities/{opp}", json={"status": "Closed"})
    dash = client.get("/api/dashboard").json()
    assert "Ask about the internship timeline" not in [a["text"] for a in dash["upcoming"]]
    energy = next(p for p in dash["pipeline"] if p["track"] == "energy")
    assert energy["total"] == 2


def test_complete_next_step_logs_it_and_sets_the_next(client):
    with db.connect() as conn:
        _, opp = _ids(conn)
    r = client.post(f"/api/opportunities/{opp}/complete",
                    json={"next_action": "Send resume to Priya", "due": "2026-12-01"}).json()
    assert r["next_action"] == "Send resume to Priya" and r["due"] == "2026-12-01"
    assert "Done " in r["notes"] and "Ask about the internship timeline" in r["notes"]
    client.post(f"/api/opportunities/{opp}/complete", json={})
    assert client.post(f"/api/opportunities/{opp}/complete", json={}).status_code == 422   # nothing left


def test_create_opportunity_takes_the_employers_track(client):
    with db.connect() as conn:
        granite, _ = _ids(conn)
    oid = client.post("/api/opportunities", json={"title": "Base Village Analyst", "employer_id": granite}).json()["id"]
    with db.connect() as conn:
        assert db.one(conn, "SELECT track, cycle FROM opportunities WHERE id = ?", (oid,)) == {
            "track": "outdoor", "cycle": "Upcoming internship"}
    assert client.post("/api/opportunities", json={"title": "x", "employer_id": 9999}).status_code == 422


def test_employers_create_edit_note_and_page(client):
    r = client.post("/api/employers", json={"name": "Crestline Hydro", "track": "energy", "path": "energy_dev"})
    eid = r.json()["id"]
    assert client.post("/api/employers", json={"name": "crestline hydro", "track": "energy"}).status_code == 422
    assert client.patch(f"/api/employers/{eid}", json={"stage": "Networking", "location": "Bend, OR"}).status_code == 200
    assert client.patch(f"/api/employers/{eid}", json={"stage": "Married"}).status_code == 422
    client.post(f"/api/employers/{eid}/notes", json={"text": "Run-of-river projects in the Cascades."})
    page = client.get(f"/api/employers/{eid}").json()
    assert page["stage"] == "Networking" and page["location"] == "Bend, OR"
    assert page["notes"][0]["text"].startswith("Run-of-river") and page["notes"][0]["contact"] is None
    assert client.get("/api/employers/9999").status_code == 404


def test_older_database_gets_new_columns(tmp_path, monkeypatch):
    old = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(old)
    conn.executescript("""CREATE TABLE opportunities (id INTEGER PRIMARY KEY, employer_id INTEGER, title TEXT NOT NULL,
        track TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Researching', next_action TEXT NOT NULL DEFAULT '',
        due TEXT NOT NULL DEFAULT ''); INSERT INTO opportunities(title, track) VALUES ('Old one', 'energy');""")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init_db()
    with db.connect() as c:
        row = db.one(c, "SELECT title, notes, cycle FROM opportunities")
    assert row == {"title": "Old one", "notes": "", "cycle": "Upcoming internship"}
