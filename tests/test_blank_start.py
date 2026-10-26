"""A blank Career HQ: welcome state, sample data, start over, Path Finder and Connections."""

import pytest
from pydantic_ai.models.test import TestModel

from app import config, connections, db, pathfinder

RANKING = ["growth", "pay", "team", "work", "lifestyle", "impact", "stability", "brand"]


@pytest.fixture
def blank(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "career_hq.sqlite3")
    db.init_db()


def answers(client, **over):
    """A complete About-you answer set: the first option of every question."""
    secs = client.get("/api/profile").json()["sections"]
    a = {q["key"]: (q["options"][0]["key"] if q["type"] == "single" else [q["options"][0]["key"]])
         for s in secs for q in s["questions"]}
    a.update(over)
    return a


def direction(name, **kw):
    d = {"name": name, "one_liner": f"{name} work.", "why_fit": "Fits your answers.",
         "example_roles": ["Associate", "Analyst", "Manager"], "employer_types": ["Startups", "Large firms", "Agencies"],
         "tradeoffs": "Lower pay at first.", "questions_to_resolve": [f"What does a week in {name} look like?",
                                                                     f"How do people break into {name}?"]}
    d.update(kw)
    return d


def test_app_starts_blank(client, blank):
    st = client.get("/api/status").json()
    assert st["empty"] is True and st["needs_setup"] is True
    assert client.get("/api/contacts").json() == []
    assert client.get("/api/tracks").json()["tracks"] == []
    assert client.get("/api/lookups").json()["paths"] == []        # no one's career paths baked in


def test_sample_loads_only_into_a_blank_hq_and_start_over_clears_it(client, blank):
    assert client.post("/api/sample").status_code == 200
    st = client.get("/api/status").json()
    assert st["empty"] is False and st["needs_setup"] is False and st["database"] == "sample"
    assert len(client.get("/api/contacts").json()) == 7
    assert client.post("/api/sample").status_code == 409             # not over the top of real data
    assert client.post("/api/reset", json={"confirm": "yes"}).status_code == 422
    with db.connect() as conn:
        conn.execute("INSERT INTO runs(created_at, model, outcome, cost_usd) VALUES (?, 'gpt-6-luna', 'ok', 0.01)", (db.now(),))
    assert client.post("/api/reset", json={"confirm": "START OVER"}).status_code == 200
    st = client.get("/api/status").json()
    assert st["empty"] is True
    assert st["spent_today_usd"] == 0.01                               # the spend log survives a reset


def test_new_user_flow_with_path_finder(client, blank):
    assert client.post("/api/directions/suggest").status_code == 409   # About you comes first
    assert client.put("/api/profile", json=answers(client, industries=["Not sure yet"])).status_code == 200
    client.put("/api/priorities", json={"ranking": RANKING, "dealbreakers": ["heavy_travel"]})
    out = {"directions": [direction("Climate tech operations"), direction("Sports business"),
                          direction("Hospital strategy"), direction("Climate tech operations"),     # duplicate
                          direction("Bad one", why_fit="Email jobs@bad.example now.")]}
    with pathfinder.build_agent().override(model=TestModel(call_tools=[], custom_output_args=out)):
        r = client.post("/api/directions/suggest").json()
    assert r["outcome"] == "ok" and r["added"] == 3
    assert sorted(b["reason"] for b in r["blocked"]) == ["contains an email address", "duplicate"]
    dirs = client.get("/api/directions").json()["directions"]
    climate = next(d for d in dirs if d["name"] == "Climate tech operations")
    saved = client.put("/api/tracks", json={"tracks": [
        {"name": "Climate tech operations", "role": "Primary focus", "blurb": climate["one_liner"], "direction_id": climate["id"]},
        {"name": "Healthcare", "role": "Exploring"}]}).json()
    assert saved["questions_added"] == 2
    assert client.get("/api/status").json()["needs_setup"] is False
    qs = client.get("/api/questions").json()
    assert [q["path"] for q in qs] == ["climate-tech-operations"] * 2   # tagged with the new track
    assert {p["key"] for p in client.get("/api/lookups").json()["paths"]} == {"climate-tech-operations", "healthcare"}
    # The picked direction isn't wiped by a fresh suggestion run; unpicked ones are.
    with pathfinder.build_agent().override(model=TestModel(call_tools=[], custom_output_args={"directions": [direction("Ed tech")]})):
        client.post("/api/directions/suggest")
    names = [d["name"] for d in client.get("/api/directions").json()["directions"]]
    assert names == ["Climate tech operations", "Ed tech"]


def test_not_sure_yet_is_a_valid_answer(client, blank):
    assert client.put("/api/profile", json=answers(client, industries=["Not sure yet"], functions=["Not sure yet"])).status_code == 200


def lead_plan():
    return {"connects": [
        {"role": "Project developer", "where": "Ridgeline Geothermal", "track": "Energy & infrastructure",
         "why": "Knows the day-to-day.", "answers_question": "", "how_to_find": "Alumni directory",
         "search_phrase": "project developer geothermal", "opening": "I'm exploring development roles."},
        {"role": "Recruiter", "where": "Any", "track": "energy", "why": "Hiring.", "answers_question": "",
         "how_to_find": "Other", "search_phrase": "see https://jobs.example/apply", "opening": "Hi."}],
        "multipliers": [
        {"name": "Western Trails Alliance", "type": "Professional association", "track": "outdoor",
         "why": "Member directory.", "effort": "Low", "cost": "Free", "next_step": "Join the free newsletter"},
        {"name": "Mystery Club", "type": "Student club", "track": "astronomy", "why": "x", "effort": "Low",
         "cost": "Free", "next_step": "Go"}]}


def test_connections_validate_and_become_tasks(client):
    with connections.build_agent().override(model=TestModel(call_tools=[], custom_output_args=lead_plan())):
        r = client.post("/api/connections/suggest").json()
    assert r["added"] == 2
    assert sorted(b["reason"] for b in r["blocked"]) == ["search phrase: contains a web link", "unknown track 'astronomy'"]
    d = client.get("/api/connections").json()
    connect, mult = d["connects"][0], d["multipliers"][0]
    assert connect["track"] == "energy" and connect["title"] == "Project developer · Ridgeline Geothermal"
    added = client.post(f"/api/connections/{connect['id']}/add").json()
    assert added["status"] == "added" and "Project developer" in added["task"]
    assert client.post(f"/api/connections/{connect['id']}/add").status_code == 409
    with db.connect() as conn:
        t = db.one(conn, """SELECT t.due, e.name FROM tasks t LEFT JOIN employers e ON e.id = t.employer_id
                            ORDER BY t.id DESC LIMIT 1""")
    assert t["name"] == "Ridgeline Geothermal" and t["due"]               # linked to the employer, dated
    assert client.post(f"/api/connections/{mult['id']}/dismiss").json()["status"] == "dismissed"
    assert client.post(f"/api/connections/{mult['id']}/undo").json()["status"] == "new"
    # The same suggestions aren't stored twice.
    with connections.build_agent().override(model=TestModel(call_tools=[], custom_output_args=lead_plan())):
        again = client.post("/api/connections/suggest").json()
    assert again["added"] == 0


def test_agent_prompts_have_no_baked_in_user():
    from app import agent, scout
    text = agent.INSTRUCTIONS + pathfinder.INSTRUCTIONS + connections.INSTRUCTIONS + scout.INSTRUCTIONS
    for word in ("MBA student", "the student", "Summer 2027", "MEM", "skiing"):
        assert word not in text
