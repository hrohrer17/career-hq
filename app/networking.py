"""The Networking Intelligence workflow: analyze a saved conversation, then apply approved changes.

Analyze:  limits check -> injection scan -> agent run -> validator -> pending proposals + run ledger.
Approve:  re-check the proposal against current records -> write exactly one record -> mark approved.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date

from . import agent, config, db, safety

# One analysis at a time, so a double-click or a script can't run several paid calls in parallel.
_run_lock = threading.Lock()


class WorkflowError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _context(conn: sqlite3.Connection, notes: str) -> safety.ValidationContext:
    return safety.ValidationContext(
        notes=notes,
        employer_ids={r["id"] for r in db.rows(conn, "SELECT id FROM employers")},
        open_question_ids={r["id"] for r in db.rows(conn, "SELECT id FROM questions WHERE status = 'open'")},
        path_keys={r["key"] for r in db.rows(conn, "SELECT key FROM paths")},
    )


def _record_run(conn, conversation_id, res: agent.RunResult, cost: float, total: int, blocked: list[dict]) -> int:
    u = res.usage
    cur = conn.execute(
        """INSERT INTO runs(created_at, conversation_id, model, outcome, input_tokens, cached_tokens,
               cache_write_tokens, output_tokens, requests, tool_calls, cost_usd, latency_ms,
               proposals_total, blocked_by_validator, blocked_reasons, tools_used, error)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (db.now(), conversation_id, config.MODEL_NAME, res.outcome, u["input_tokens"], u["cached_tokens"],
         u["cache_write_tokens"], u["output_tokens"], u["requests"], u["tool_calls"], cost, res.latency_ms,
         total, len(blocked), json.dumps(blocked), json.dumps(res.tools_used), res.error))
    return cur.lastrowid


def analyze(conversation_id: int) -> dict:
    if not _run_lock.acquire(blocking=False):
        raise WorkflowError(429, "Another analysis is already running. Wait for it to finish.")
    try:
        with db.connect() as conn:
            conv = db.one(conn, "SELECT * FROM conversations WHERE id = ?", (conversation_id,))
            if conv is None:
                raise WorkflowError(404, "Conversation not found.")
            if db.one(conn, "SELECT 1 FROM proposals WHERE conversation_id = ? AND status = 'pending'",
                      (conversation_id,)):
                raise WorkflowError(409, "Review the pending suggestions for this conversation first.")
            try:
                safety.check_limits(conn, conversation_id)
            except safety.LimitReached as exc:
                raise WorkflowError(429, str(exc)) from exc
            flagged = safety.suspicious_sentences(conv["notes"])
            conn.execute("UPDATE conversations SET injection_flag = ? WHERE id = ?",
                         (json.dumps(flagged) if flagged else "", conversation_id))

        # The model call happens outside any open database transaction.
        res = agent.run_debrief(conv["contact_id"], conversation_id, conv["notes"], conv["occurred_on"],
                                date.today().isoformat())

        with db.connect() as conn:
            u = res.usage
            cost = safety.cost_usd(u["input_tokens"], u["cached_tokens"], u["cache_write_tokens"], u["output_tokens"])
            if res.outcome != "ok":
                status = "blocked" if res.outcome == "blocked_filter" else "failed"
                run_id = _record_run(conn, conversation_id, res, cost, 0, [])
                conn.execute("UPDATE conversations SET analysis_status = ? WHERE id = ?", (status, conversation_id))
                return {"outcome": res.outcome, "message": res.error, "run_id": run_id,
                        "flagged_sentences": flagged}

            raw = [c.model_dump() for c in res.output.changes]
            verdict = safety.validate_changes(raw, _context(conn, conv["notes"]))
            run_id = _record_run(conn, conversation_id, res, cost, len(raw), verdict.blocked)
            for item in verdict.accepted:
                payload = {k: v for k, v in item.items() if k not in ("kind", "evidence", "rationale")}
                conn.execute(
                    """INSERT INTO proposals(conversation_id, run_id, kind, payload, evidence, rationale)
                       VALUES (?,?,?,?,?,?)""",
                    (conversation_id, run_id, item["kind"], json.dumps(payload), item["evidence"], item["rationale"]))
            model_flag = res.output.notes_contain_instructions
            if model_flag and not flagged:
                flagged = ["The AI reported text in these notes addressed to an AI."]
                conn.execute("UPDATE conversations SET injection_flag = ? WHERE id = ?",
                             (json.dumps(flagged), conversation_id))
            conn.execute("UPDATE conversations SET analysis_status = 'analyzed' WHERE id = ?", (conversation_id,))
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                         (f"summary:{conversation_id}", res.output.summary[:600]))
            return {"outcome": "ok", "run_id": run_id, "summary": res.output.summary,
                    "accepted": len(verdict.accepted), "blocked": verdict.blocked,
                    "flagged_sentences": flagged, "model_flagged_instructions": model_flag}
    finally:
        _run_lock.release()


def decide(proposal_id: int, approve: bool, edited_text: str | None = None) -> dict:
    with db.connect() as conn:
        p = db.one(conn, """SELECT p.*, c.contact_id FROM proposals p
                            JOIN conversations c ON c.id = p.conversation_id WHERE p.id = ?""", (proposal_id,))
        if p is None:
            raise WorkflowError(404, "Suggestion not found.")
        if p["status"] != "pending":
            raise WorkflowError(409, f"Already {p['status']}.")
        if not approve:
            conn.execute("UPDATE proposals SET status = 'rejected', decided_at = ? WHERE id = ?", (db.now(), proposal_id))
            return {"status": "rejected"}

        payload = json.loads(p["payload"])
        text = payload["text"]
        if edited_text is not None and edited_text.strip() != text:
            text = edited_text.strip()
            reason = safety.check_text(p["kind"], text)
            if reason:
                raise WorkflowError(422, f"Edited text not saved: {reason}.")
        ref = _apply(conn, p, payload, text)
        conn.execute("UPDATE proposals SET status = 'approved', decided_at = ?, applied_ref = ?, payload = ? WHERE id = ?",
                     (db.now(), ref, json.dumps({**payload, "text": text}), proposal_id))
        return {"status": "approved", "applied_ref": ref}


def _apply(conn: sqlite3.Connection, p: dict, payload: dict, text: str) -> str:
    """Write the one record this proposal describes. Targets are re-checked against current data."""
    ts, conv_id, kind = db.now(), p["conversation_id"], p["kind"]
    employer_id = payload.get("employer_id")
    if employer_id is not None and not db.one(conn, "SELECT 1 FROM employers WHERE id = ?", (employer_id,)):
        raise WorkflowError(409, "That employer no longer exists.")

    if kind == "task":
        cur = conn.execute(
            """INSERT INTO tasks(description, due, contact_id, employer_id, conversation_id, created_at)
               VALUES (?,?,?,?,?,?)""", (text, payload.get("due") or "", p["contact_id"], employer_id, conv_id, ts))
        return f"task:{cur.lastrowid}"
    if kind == "contact_note":
        # Always the person this conversation was with; the model cannot pick a different contact.
        cur = conn.execute("INSERT INTO contact_notes(contact_id, text, conversation_id, created_at) VALUES (?,?,?,?)",
                           (p["contact_id"], text, conv_id, ts))
        return f"contact_note:{cur.lastrowid}"
    if kind == "learning":
        cur = conn.execute(
            """INSERT INTO learnings(text, evidence, path, employer_id, conversation_id, created_at)
               VALUES (?,?,?,?,?,?)""", (text, p["evidence"], payload.get("path"), employer_id, conv_id, ts))
        return f"learning:{cur.lastrowid}"
    if kind == "new_question":
        cur = conn.execute(
            """INSERT INTO questions(text, why, path, employer_id, created_conversation_id, created_at)
               VALUES (?,?,?,?,?,?)""", (text, p["rationale"], payload.get("path"), employer_id, conv_id, ts))
        return f"question:{cur.lastrowid}"
    if kind == "answer_question":
        qid = payload.get("question_id")
        cur = conn.execute(
            """UPDATE questions SET status = 'answered', answer = ?, answered_conversation_id = ?, answered_at = ?
               WHERE id = ? AND status = 'open'""", (text, conv_id, ts, qid))
        if cur.rowcount != 1:
            raise WorkflowError(409, "That question is no longer open.")
        return f"question:{qid}"
    if kind == "employer_note":
        cur = conn.execute("INSERT INTO employer_notes(employer_id, text, conversation_id, created_at) VALUES (?,?,?,?)",
                           (employer_id, text, conv_id, ts))
        return f"employer_note:{cur.lastrowid}"
    raise WorkflowError(400, f"Unknown change type {kind}.")
