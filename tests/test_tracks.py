"""Configurable tracks: a new user sets up 1-3; edits keep records attached; old databases upgrade."""

import sqlite3

import pytest

from app import config, db


@pytest.fixture
def new_user(tmp_path, monkeypatch):
    """A private database: no demo records, no tracks yet."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "me.sqlite3")
    db.init_db()


def put(client, tracks):
    return client.put("/api/tracks", json={"tracks": tracks})


def test_new_user_must_set_up_tracks_first(client, new_user):
    assert client.get("/api/status").json()["needs_setup"] is True
    assert client.get("/api/internships").json()["tracks"] == []
    r = put(client, [{"name": "Sports business", "role": "Primary focus"},
                     {"name": "Consulting", "role": "Strong alternative"},
                     {"name": "Technology", "role": "Exploring"}])
    assert r.status_code == 200
    saved = r.json()["tracks"]
    assert [t["key"] for t in saved] == ["sports-business", "consulting", "technology"]
    assert [t["short"] for t in saved] == ["Sports", "Consulting", "Tech"]
    assert saved[1]["blurb"] == "Strategy and management consulting."    # filled from the preset
    # Setup isn't finished until the priorities are ranked too.
    assert client.get("/api/status").json()["needs_setup"] is True
    ranking = ["work", "pay", "lifestyle", "impact", "team", "growth", "stability", "brand"]
    assert client.put("/api/priorities", json={"ranking": ranking, "dealbreakers": []}).status_code == 200
    assert client.get("/api/status").json()["needs_setup"] is False
    ihq = client.get("/api/internships").json()
    assert [t["name"] for t in ihq["tracks"]] == ["Sports business", "Consulting", "Technology"]
    assert len(client.get("/api/dashboard").json()["pipeline"]) == 3


def test_one_track_is_always_primary(client, new_user):
    saved = put(client, [{"name": "Healthcare", "role": "Exploring"}]).json()["tracks"]
    assert saved[0]["role"] == "Primary focus"


@pytest.mark.parametrize("tracks, message", [
    ([], "between 1 and 3"),
    ([{"name": f"T{i}", "role": "Exploring"} for i in range(4)], "between 1 and 3"),
    ([{"name": "", "role": "Primary focus"}], "needs a name"),
    ([{"name": "A", "role": "Primary focus"}, {"name": "a", "role": "Exploring"}], "different name"),
    ([{"name": "A", "role": "Primary focus"}, {"name": "B", "role": "Primary focus"}], "exactly one"),
    ([{"name": "A", "role": "Exploring"}, {"name": "B", "role": "Exploring"}], "exactly one"),
    ([{"name": "A", "role": "Boss"}, {"name": "B", "role": "Primary focus"}], "Choose a role"),
])
def test_bad_setups_are_refused(client, new_user, tracks, message):
    r = put(client, tracks)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_employers_must_use_an_existing_track(client, new_user):
    put(client, [{"name": "Consulting", "role": "Primary focus"}])
    assert client.post("/api/employers", json={"name": "Acme", "track": "energy"}).status_code == 422
    assert client.post("/api/employers", json={"name": "Acme", "track": "consulting"}).status_code == 200


def test_rename_keeps_records_and_removal_is_blocked_while_in_use(client):
    # Demo database: outdoor + energy, with employers on both.
    tracks = client.get("/api/tracks").json()["tracks"]
    assert [t["key"] for t in tracks] == ["outdoor", "energy"] and all(t["in_use"] for t in tracks)
    renamed = put(client, [{"key": "outdoor", "name": "Outdoor & mountain towns", "role": "Primary focus"},
                           {"key": "energy", "name": "Energy & infrastructure", "role": "Strong alternative"}])
    assert renamed.status_code == 200
    ihq = client.get("/api/internships").json()
    assert ihq["tracks"][0]["name"] == "Outdoor & mountain towns" and len(ihq["tracks"][0]["employers"]) == 4

    r = put(client, [{"key": "outdoor", "name": "Outdoor recreation", "role": "Primary focus"}])
    assert r.status_code == 409 and "still has" in r.json()["detail"]
    assert len(client.get("/api/tracks").json()["tracks"]) == 2          # nothing changed

    # Reorder and add a third: positions follow the new order.
    saved = put(client, [{"key": "energy", "name": "Energy & infrastructure", "role": "Primary focus"},
                         {"key": "outdoor", "name": "Outdoor recreation", "role": "Strong alternative"},
                         {"name": "Real estate & development", "role": "Exploring"}]).json()["tracks"]
    assert [(t["key"], t["position"]) for t in saved] == [("energy", 1), ("outdoor", 2), ("real-estate-development", 3)]

    # An unused track can be removed.
    assert put(client, [{"key": "energy", "name": "Energy & infrastructure", "role": "Primary focus"},
                        {"key": "outdoor", "name": "Outdoor recreation", "role": "Strong alternative"}]).status_code == 200


def test_tracks_reach_the_agent_prompt():
    from app import agent
    assert agent.track_list()[0]["name"] == "Outdoor recreation"


def test_database_with_fixed_tracks_is_upgraded(tmp_path, monkeypatch):
    old = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(old)
    conn.executescript("""
        CREATE TABLE employers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            track TEXT NOT NULL CHECK (track IN ('outdoor', 'energy')), path TEXT, location TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT 'Researching', summary TEXT NOT NULL DEFAULT '');
        CREATE TABLE opportunities (id INTEGER PRIMARY KEY, employer_id INTEGER REFERENCES employers(id),
            title TEXT NOT NULL, track TEXT NOT NULL CHECK (track IN ('outdoor', 'energy')),
            status TEXT NOT NULL DEFAULT 'Researching', next_action TEXT NOT NULL DEFAULT '', due TEXT NOT NULL DEFAULT '');
        CREATE TABLE contacts (id INTEGER PRIMARY KEY, name TEXT NOT NULL, employer_id INTEGER REFERENCES employers(id),
            role TEXT NOT NULL DEFAULT '', how_met TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '');
        INSERT INTO employers(name, track) VALUES ('Old Energy Co', 'energy');
        INSERT INTO opportunities(employer_id, title, track) VALUES (1, 'Old intern role', 'energy');
        INSERT INTO contacts(name, employer_id) VALUES ('Old Contact', 1);""")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init_db()
    with db.connect() as c:
        sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'employers'").fetchone()[0]
        assert "CHECK (track" not in sql
        assert db.rows(c, "SELECT key, name FROM tracks") == [{"key": "energy", "name": "Energy & infrastructure"}]
        assert db.one(c, "SELECT e.name FROM contacts c JOIN employers e ON e.id = c.employer_id")["name"] == "Old Energy Co"
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        c.execute("INSERT INTO tracks(key, name, short, role, position) VALUES ('tech', 'Tech', 'Tech', 'Exploring', 2)")
        c.execute("INSERT INTO employers(name, track) VALUES ('New Tech Co', 'tech')")   # no longer blocked
