"""Career HQ web server: JSON API plus the single-page website.

Run from the repo folder:  python -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import (config, connections, dashboard, db, decisions, internships, networking, pathfinder, profile, safety,
               scout, tracks)

db.init_db()
app = FastAPI(title="Career HQ", version="2.0")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.middleware("http")
async def no_stale_pages(request, call_next):
    # Revalidate the page, script and styles on every load, so an updated app is never half old.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(networking.WorkflowError)
def workflow_error(_request, exc: networking.WorkflowError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


@app.exception_handler(internships.InvalidInput)
def invalid_input(_request, exc: internships.InvalidInput):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(tracks.TrackError)
def track_error(_request, exc: tracks.TrackError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.exception_handler(decisions.DecisionError)
def decision_error(_request, exc: decisions.DecisionError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(profile.ProfileError)
def profile_error(_request, exc: profile.ProfileError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(scout.ScoutError)
@app.exception_handler(pathfinder.PathError)
@app.exception_handler(connections.ConnectionsError)
def feature_error(_request, exc):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


@app.exception_handler(internships.NotFound)
def not_found(_request, exc: internships.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


# ---------- request bodies ----------

def _iso_date(v: str) -> str:
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError as exc:
        raise ValueError("use YYYY-MM-DD") from exc


class ConversationIn(BaseModel):
    occurred_on: str = Field(default_factory=lambda: date.today().isoformat())
    notes: str = Field(min_length=config.MIN_NOTE_CHARS, max_length=config.MAX_NOTE_CHARS)

    @field_validator("occurred_on")
    @classmethod
    def _check_date(cls, v: str) -> str:
        return _iso_date(v)


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    employer_id: int | None = None
    role: str = Field(default="", max_length=160)
    how_met: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=160)


class DecisionIn(BaseModel):
    text: str | None = Field(default=None, max_length=600)


class TrackIn(BaseModel):
    key: str | None = None
    direction_id: int | None = None   # set when the track came from a Path Finder suggestion
    name: str = Field(default="", max_length=60)
    short: str = Field(default="", max_length=14)
    role: str = ""
    blurb: str = Field(default="", max_length=200)


class TracksIn(BaseModel):
    tracks: list[TrackIn] = Field(max_length=10)


class PrioritiesIn(BaseModel):
    ranking: list[str] = Field(max_length=20)
    dealbreakers: list[str] = Field(default_factory=list, max_length=20)


class WeightIn(BaseModel):
    weight: float


class ScoreIn(BaseModel):
    score: int | None = None
    note: str = Field(default="", max_length=300)


class DealbreakersIn(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=20)


class ResetIn(BaseModel):
    confirm: str


class ReactionIn(BaseModel):
    reaction: str | None = None


class EmployerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    track: str
    path: str | None = None
    location: str = Field(default="", max_length=160)
    stage: str = "Researching"
    summary: str = Field(default="", max_length=1000)


class EmployerPatch(BaseModel):
    track: str | None = None
    path: str | None = None
    location: str | None = Field(default=None, max_length=160)
    stage: str | None = None
    summary: str | None = Field(default=None, max_length=1000)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class OpportunityIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    employer_id: int | None = None
    track: str | None = None
    status: str = "Researching"
    cycle: str = "Upcoming internship"
    next_action: str = Field(default="", max_length=200)
    due: str = ""
    notes: str = Field(default="", max_length=4000)


class OpportunityPatch(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    employer_id: int | None = None
    status: str | None = None
    cycle: str | None = None
    next_action: str | None = Field(default=None, max_length=200)
    due: str | None = None
    notes: str | None = Field(default=None, max_length=4000)


class CompleteIn(BaseModel):
    next_action: str = Field(default="", max_length=200)
    due: str = ""


class TaskIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    due: str = ""
    contact_id: int | None = None


# ---------- reads ----------

@app.get("/api/status")
def status():
    with db.connect() as conn:
        spent = safety.spent_today(conn)
        needs_setup = not tracks.all_tracks(conn) or not decisions.has_priorities(conn)
        empty = db.is_empty(conn)
        sample = db.setting(conn, "sample_notes") != ""
    return {"needs_setup": needs_setup, "empty": empty, "model": config.MODEL_NAME, "key_source": config.key_source(),
            "ai_ready": config.api_credentials() is not None, "today": date.today().isoformat(),
            "spent_today_usd": round(spent, 6), "daily_budget_usd": config.DAILY_BUDGET_USD,
            "max_runs_per_hour": config.MAX_RUNS_PER_HOUR, "max_note_chars": config.MAX_NOTE_CHARS,
            "database": "sample" if sample else "yours"}


@app.get("/api/dashboard")
def get_dashboard():
    with db.connect() as conn:
        return dashboard.build(conn)


@app.get("/api/tracks")
def get_tracks():
    with db.connect() as conn:
        current = tracks.all_tracks(conn)
        for t in current:
            t["in_use"] = conn.execute(
                "SELECT (SELECT COUNT(*) FROM employers WHERE track = ?) + (SELECT COUNT(*) FROM opportunities WHERE track = ?)",
                (t["key"], t["key"])).fetchone()[0]
    return {"tracks": current, "presets": tracks.PRESETS, "roles": tracks.ROLES,
            "min": tracks.MIN_TRACKS, "max": tracks.MAX_TRACKS}


@app.put("/api/tracks")
def put_tracks(body: TracksIn):
    items = [t.model_dump() for t in body.tracks]
    with db.connect() as conn:
        saved = tracks.save(conn, items)
        by_name = {t["name"].lower(): t["key"] for t in saved}
        seeded = 0
        for it in items:
            if it.get("direction_id") and it["name"].strip().lower() in by_name:
                seeded += pathfinder.seed_questions(conn, it["direction_id"], by_name[it["name"].strip().lower()])
        return {"tracks": saved, "questions_added": seeded}


@app.get("/api/directions")
def get_directions():
    with db.connect() as conn:
        return {"directions": pathfinder.listing(conn)}


@app.post("/api/directions/suggest")
def suggest_directions():
    if config.api_credentials() is None:
        raise HTTPException(503, "No AI key found. Add PORTKEY_API_KEY to a .env file (see README).")
    return pathfinder.suggest()


@app.get("/api/connections")
def get_connections():
    with db.connect() as conn:
        return connections.listing(conn)


@app.post("/api/connections/suggest")
def suggest_connections():
    if config.api_credentials() is None:
        raise HTTPException(503, "No AI key found. Add PORTKEY_API_KEY to a .env file (see README).")
    return connections.suggest()


class FoundIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=160)
    employer_id: int | None = None


@app.post("/api/connections/{lead_id}/contact")
def lead_to_contact(lead_id: int, body: FoundIn):
    with db.connect() as conn:
        return {"contact_id": connections.make_contact(conn, lead_id, body.name, body.role, body.employer_id)}


@app.post("/api/connections/{lead_id}/{action}")
def act_on_lead(lead_id: int, action: str):
    with db.connect() as conn:
        return connections.act(conn, lead_id, action)


@app.get("/api/priorities")
def get_priorities():
    with db.connect() as conn:
        return {"criteria": decisions.criteria(conn), "dealbreakers": decisions.selected_dealbreakers(conn),
                "dealbreaker_options": decisions.DEALBREAKERS, "rank_weights": decisions.RANK_WEIGHTS}


@app.put("/api/priorities")
def put_priorities(body: PrioritiesIn):
    with db.connect() as conn:
        decisions.save_priorities(conn, body.ranking, body.dealbreakers)
        return {"criteria": decisions.criteria(conn)}


@app.patch("/api/criteria/{key}")
def patch_weight(key: str, body: WeightIn):
    with db.connect() as conn:
        decisions.set_weight(conn, key, body.weight)
        return {"criteria": decisions.criteria(conn)}


@app.post("/api/criteria/reset")
def reset_weights():
    with db.connect() as conn:
        decisions.reset_weights(conn)
        return {"criteria": decisions.criteria(conn)}


@app.get("/api/decisions")
def get_decisions():
    with db.connect() as conn:
        return decisions.studio(conn)


@app.put("/api/employers/{employer_id}/scores/{key}")
def put_score(employer_id: int, key: str, body: ScoreIn):
    with db.connect() as conn:
        decisions.set_score(conn, employer_id, key, body.score, body.note)
        return {"ok": True}


@app.put("/api/employers/{employer_id}/dealbreakers")
def put_employer_dealbreakers(employer_id: int, body: DealbreakersIn):
    with db.connect() as conn:
        decisions.set_employer_dealbreakers(conn, employer_id, body.keys)
        return {"ok": True}


@app.post("/api/sample")
def load_sample():
    with db.connect() as conn:
        try:
            db.load_sample(conn)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@app.post("/api/reset")
def reset(body: ResetIn):
    """Start over: delete everything the user made. Needs the word START OVER typed back."""
    if body.confirm != "START OVER":
        raise HTTPException(422, 'Type START OVER to confirm.')
    with db.connect() as conn:
        db.reset_all(conn)
    return {"ok": True}


@app.get("/api/profile")
def get_profile():
    with db.connect() as conn:
        return {"sections": profile.SECTIONS, "answers": profile.get(conn),
                "max_known_employers": profile.MAX_KNOWN_EMPLOYERS}


@app.put("/api/profile")
def put_profile(body: dict):
    with db.connect() as conn:
        return {"answers": profile.save(conn, body)}


@app.get("/api/targets")
def get_targets():
    with db.connect() as conn:
        return scout.board(conn)


@app.post("/api/targets/suggest")
def suggest_targets():
    if config.api_credentials() is None:
        raise HTTPException(503, "No AI key found. Add PORTKEY_API_KEY to a .env file (see README).")
    return scout.suggest()


@app.put("/api/targets/{candidate_id}/reaction")
def react_to_target(candidate_id: int, body: ReactionIn):
    with db.connect() as conn:
        scout.react(conn, candidate_id, body.reaction)
        return {"ok": True}


@app.post("/api/targets/add-top")
def add_top_targets():
    with db.connect() as conn:
        return scout.add_top(conn)


@app.get("/api/internships")
def get_internships():
    with db.connect() as conn:
        return internships.overview(conn)


@app.get("/api/employers/{employer_id}")
def get_employer(employer_id: int):
    with db.connect() as conn:
        e = internships.employer_page(conn, employer_id)
    if e is None:
        raise HTTPException(404, "Employer not found.")
    return e


@app.get("/api/lookups")
def lookups():
    with db.connect() as conn:
        return {"employers": db.rows(conn, "SELECT id, name, track, path FROM employers ORDER BY name"),
                "tracks": tracks.all_tracks(conn),
                "paths": db.rows(conn, "SELECT key, name FROM paths")}


@app.get("/api/contacts")
def list_contacts():
    with db.connect() as conn:
        return db.rows(conn, """
            SELECT c.id, c.name, c.role, e.name AS employer, e.track,
                   (SELECT MAX(occurred_on) FROM conversations WHERE contact_id = c.id) AS last_contacted,
                   (SELECT COUNT(*) FROM conversations WHERE contact_id = c.id) AS conversations,
                   (SELECT COUNT(*) FROM proposals p JOIN conversations v ON v.id = p.conversation_id
                     WHERE v.contact_id = c.id AND p.status = 'pending') AS pending,
                   (SELECT COUNT(*) FROM tasks WHERE contact_id = c.id AND status = 'open') AS open_tasks
            FROM contacts c LEFT JOIN employers e ON e.id = c.employer_id
            ORDER BY (last_contacted IS NULL), last_contacted DESC, c.name""")


def _proposal_view(p: dict) -> dict:
    payload = json.loads(p["payload"])
    return {"id": p["id"], "kind": p["kind"], "status": p["status"], "evidence": p["evidence"],
            "rationale": p["rationale"], "decided_at": p["decided_at"], **payload}


@app.get("/api/contacts/{contact_id}")
def contact_profile(contact_id: int):
    with db.connect() as conn:
        c = db.one(conn, """SELECT c.*, e.name AS employer, e.track, e.stage AS employer_stage
                            FROM contacts c LEFT JOIN employers e ON e.id = c.employer_id WHERE c.id = ?""",
                   (contact_id,))
        if c is None:
            raise HTTPException(404, "Contact not found.")
        convs = db.rows(conn, "SELECT * FROM conversations WHERE contact_id = ? ORDER BY occurred_on DESC, id DESC",
                        (contact_id,))
        questions = {q["id"]: q["text"] for q in db.rows(conn, "SELECT id, text FROM questions")}
        employers = {e["id"]: e["name"] for e in db.rows(conn, "SELECT id, name FROM employers")}
        for cv in convs:
            cv["injection_flag"] = json.loads(cv["injection_flag"]) if cv["injection_flag"] else []
            cv["summary"] = db.setting(conn, f"summary:{cv['id']}")
            props = [_proposal_view(p) for p in db.rows(
                conn, "SELECT * FROM proposals WHERE conversation_id = ? ORDER BY id", (cv["id"],))]
            for p in props:
                if p.get("question_id"):
                    p["question_text"] = questions.get(p["question_id"], "")
                if p.get("employer_id"):
                    p["employer_name"] = employers.get(p["employer_id"], "")
            cv["proposals"] = props
            last = db.one(conn, "SELECT * FROM runs WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", (cv["id"],))
            if last:
                last["blocked_reasons"] = json.loads(last["blocked_reasons"])
                last["tools_used"] = json.loads(last["tools_used"])
            cv["last_run"] = last
        c["conversations"] = convs
        c["notes"] = db.rows(conn, """SELECT n.id, n.text, n.created_at, n.conversation_id, v.occurred_on
                                      FROM contact_notes n LEFT JOIN conversations v ON v.id = n.conversation_id
                                      WHERE n.contact_id = ? ORDER BY n.id DESC""", (contact_id,))
        c["tasks"] = db.rows(conn, "SELECT * FROM tasks WHERE contact_id = ? ORDER BY status, due = '', due",
                             (contact_id,))
        c["learnings"] = db.rows(conn, """SELECT l.* FROM learnings l JOIN conversations v ON v.id = l.conversation_id
                                          WHERE v.contact_id = ? ORDER BY l.id DESC""", (contact_id,))
        c["questions_answered"] = db.rows(conn, """SELECT q.* FROM questions q
                                                   JOIN conversations v ON v.id = q.answered_conversation_id
                                                   WHERE v.contact_id = ? ORDER BY q.answered_at DESC""", (contact_id,))
        samples = json.loads(db.setting(conn, "sample_notes", "{}"))
        c["has_sample_notes"] = _sample_key(c["name"]) in samples
        return c


def _sample_key(name: str) -> str:
    return name.split()[0].lower()


@app.get("/api/contacts/{contact_id}/sample-notes")
def sample_notes(contact_id: int):
    with db.connect() as conn:
        c = db.one(conn, "SELECT name FROM contacts WHERE id = ?", (contact_id,))
        samples = json.loads(db.setting(conn, "sample_notes", "{}"))
    if c is None or _sample_key(c["name"]) not in samples:
        raise HTTPException(404, "No sample notes for this contact.")
    return {"notes": samples[_sample_key(c["name"])]}


@app.get("/api/questions")
def list_questions():
    with db.connect() as conn:
        return db.rows(conn, """SELECT q.*, e.name AS employer, p.name AS path_name FROM questions q
                                LEFT JOIN employers e ON e.id = q.employer_id LEFT JOIN paths p ON p.key = q.path
                                ORDER BY q.status DESC, q.id""")


@app.get("/api/usage")
def usage():
    with db.connect() as conn:
        runs = db.rows(conn, """SELECT r.*, CASE r.kind WHEN 'scout' THEN 'Target Scout' WHEN 'pathfinder' THEN 'Path Finder'
                    WHEN 'connections' THEN 'Connections' ELSE c.name END AS contact,
                    (SELECT COUNT(*) FROM proposals WHERE run_id = r.id AND status = 'approved') AS approved,
                    (SELECT COUNT(*) FROM proposals WHERE run_id = r.id AND status = 'rejected') AS rejected,
                    (SELECT COUNT(*) FROM proposals WHERE run_id = r.id AND status = 'pending') AS pending
                FROM runs r LEFT JOIN conversations v ON v.id = r.conversation_id
                LEFT JOIN contacts c ON c.id = v.contact_id ORDER BY r.id DESC""")
        for r in runs:
            r["blocked_reasons"] = json.loads(r["blocked_reasons"])
            r["tools_used"] = json.loads(r["tools_used"])
        ok = [r for r in runs if r["outcome"] == "ok" and r["kind"] == "debrief"]   # averages: analyses only
        n = len(ok) or 1
        totals = {k: sum(r[k] for r in runs) for k in
                  ("input_tokens", "cached_tokens", "output_tokens", "cost_usd", "approved", "rejected",
                   "blocked_by_validator", "proposals_total")}
        totals["runs"] = sum(1 for r in runs if r["kind"] == "debrief")
        totals["ok_runs"] = len(ok)
        totals["scout_runs"] = sum(1 for r in runs if r["kind"] == "scout")
        averages = {k: round(sum(r[k] for r in ok) / n, 6 if k == "cost_usd" else 0) for k in
                    ("input_tokens", "cached_tokens", "output_tokens", "cost_usd", "latency_ms")}
        return {"runs": runs, "totals": totals, "averages_ok_runs": averages,
                "spent_today_usd": safety.spent_today(conn), "daily_budget_usd": config.DAILY_BUDGET_USD,
                "prices_per_million": config.PRICE_PER_M}


# ---------- writes ----------

@app.post("/api/contacts")
def create_contact(body: ContactIn):
    with db.connect() as conn:
        if body.employer_id is not None and not db.one(conn, "SELECT 1 FROM employers WHERE id = ?", (body.employer_id,)):
            raise HTTPException(422, "Unknown employer.")
        cur = conn.execute("INSERT INTO contacts(name, employer_id, role, how_met, email) VALUES (?,?,?,?,?)",
                           (body.name.strip(), body.employer_id, body.role.strip(), body.how_met.strip(),
                            body.email.strip()))
        return {"id": cur.lastrowid}


@app.post("/api/contacts/{contact_id}/conversations")
def add_conversation(contact_id: int, body: ConversationIn):
    """Save notes first, always. Analysis is a separate step, so a failed AI call never loses notes."""
    with db.connect() as conn:
        if not db.one(conn, "SELECT 1 FROM contacts WHERE id = ?", (contact_id,)):
            raise HTTPException(404, "Contact not found.")
        cur = conn.execute("INSERT INTO conversations(contact_id, occurred_on, notes, created_at) VALUES (?,?,?,?)",
                           (contact_id, body.occurred_on, body.notes.strip(), db.now()))
        return {"id": cur.lastrowid}


@app.post("/api/conversations/{conversation_id}/analyze")
def analyze_conversation(conversation_id: int):
    if config.api_credentials() is None:
        raise HTTPException(503, "No AI key found. Add PORTKEY_API_KEY to a .env file (see README).")
    return networking.analyze(conversation_id)


@app.post("/api/proposals/{proposal_id}/approve")
def approve(proposal_id: int, body: DecisionIn | None = None):
    return networking.decide(proposal_id, True, body.text if body else None)


@app.post("/api/proposals/{proposal_id}/reject")
def reject(proposal_id: int):
    return networking.decide(proposal_id, False)


@app.post("/api/employers")
def create_employer(body: EmployerIn):
    with db.connect() as conn:
        return {"id": internships.create_employer(conn, body.model_dump())}


@app.patch("/api/employers/{employer_id}")
def patch_employer(employer_id: int, body: EmployerPatch):
    with db.connect() as conn:
        internships.update_employer(conn, employer_id, body.model_dump(exclude_unset=True))
        return {"ok": True}


@app.post("/api/employers/{employer_id}/notes")
def add_employer_note(employer_id: int, body: NoteIn):
    with db.connect() as conn:
        return {"id": internships.add_employer_note(conn, employer_id, body.text)}


@app.post("/api/opportunities")
def create_opportunity(body: OpportunityIn):
    data = body.model_dump()
    if data["track"] is None:
        data.pop("track")
    with db.connect() as conn:
        return {"id": internships.create_opportunity(conn, data)}


@app.patch("/api/opportunities/{opp_id}")
def patch_opportunity(opp_id: int, body: OpportunityPatch):
    with db.connect() as conn:
        return internships.update_opportunity(conn, opp_id, body.model_dump(exclude_unset=True))


@app.post("/api/opportunities/{opp_id}/complete")
def complete_opportunity_action(opp_id: int, body: CompleteIn):
    with db.connect() as conn:
        return internships.complete_next_action(conn, opp_id, body.next_action.strip(), body.due)


@app.post("/api/tasks")
def create_task(body: TaskIn):
    due = _iso_date(body.due) if body.due else ""
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO tasks(description, due, contact_id, created_at) VALUES (?,?,?,?)",
                           (body.description.strip(), due, body.contact_id, db.now()))
        return {"id": cur.lastrowid}


@app.post("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int):
    with db.connect() as conn:
        t = db.one(conn, "SELECT status FROM tasks WHERE id = ?", (task_id,))
        if t is None:
            raise HTTPException(404, "Task not found.")
        new = "open" if t["status"] == "done" else "done"
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (new, task_id))
        return {"status": new}
