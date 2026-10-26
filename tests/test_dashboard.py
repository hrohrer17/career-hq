"""The Dashboard data: buckets by due date, follow-ups vs. other actions, pipeline counts."""

from datetime import date, timedelta

from app import dashboard, db


def _build(today=None):
    with db.connect() as conn:
        return dashboard.build(conn, today)


def test_demo_dates_are_relative_to_today():
    with db.connect() as conn:
        dues = {t["description"]: t["due"] for t in db.rows(conn, "SELECT description, due FROM tasks")}
    assert dues["Send thank-you note to Elena Vasquez"] == (date.today() + timedelta(days=1)).isoformat()
    assert dues["Add project-development bullets to resume"] == (date.today() - timedelta(days=2)).isoformat()


def test_upcoming_has_overdue_first_and_skips_people_tasks():
    d = _build()
    assert d["upcoming"][0]["bucket"] == "overdue"
    assert [a["due"] for a in d["upcoming"]] == sorted(a["due"] for a in d["upcoming"])
    texts = [a["text"] for a in d["upcoming"]]
    assert "Send thank-you note to Elena Vasquez" not in texts          # tied to a person -> follow-ups
    assert "Ask about the internship timeline" in texts                  # an opportunity's next step
    assert all(a["bucket"] in ("overdue", "this_week", "next_week") for a in d["upcoming"])
    assert d["later_count"] == 1                                         # Granite Peak, 21 days out


def test_followups_are_tasks_tied_to_people():
    d = _build()
    assert {f["name"] for f in d["followups"]} == {"Elena Vasquez", "Tom Brennan"}
    with db.connect() as conn:
        tid = db.one(conn, "SELECT id FROM tasks WHERE description LIKE 'Send thank-you%'")["id"]
        conn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (tid,))
    assert {f["name"] for f in _build()["followups"]} == {"Tom Brennan"}


def test_pending_reviews_show_up():
    with db.connect() as conn:
        conv = db.one(conn, "SELECT id FROM conversations LIMIT 1")["id"]
        conn.execute("INSERT INTO proposals(conversation_id, kind, payload, evidence) VALUES (?, 'task', '{\"text\": \"x\"}', 'y')",
                     (conv,))
    reviews = _build()["reviews"]
    assert len(reviews) == 1 and reviews[0]["pending"] == 1


def test_pipeline_counts_and_order():
    d = _build()
    energy = next(p for p in d["pipeline"] if p["track"] == "energy")
    assert energy["total"] == 3 and energy["furthest_stage"] == "Applied"
    assert energy["opportunities"][0]["status"] == "Applied"              # furthest along first
    assert sum(energy["counts"].values()) == 3
    assert d["learning"] == {"answered": 0, "total": 6, "next_question": d["learning"]["next_question"]}


def test_dashboard_endpoint(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200 and r.json()["today"] == date.today().isoformat()
