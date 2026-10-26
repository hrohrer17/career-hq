"""Server-side safety checks. None of these trust the model.

1. Spending guard: a daily dollar budget, a runs-per-hour cap, and a per-conversation cap,
   all checked before any model call.
2. Injection scan: flags sentences in the notes that try to give the AI orders.
3. Proposal validator: every suggested change must quote the notes exactly, use an allowed
   change type, point at records that exist, and not carry contact data or secrets anywhere.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config

ALLOWED_KINDS = ("task", "contact_note", "learning", "new_question", "answer_question", "employer_note")
MAX_ANALYSES_PER_CONVERSATION = 3


class LimitReached(Exception):
    """A spending or rate limit stopped the run before it started."""


# ---------- 1. Spending guard ----------

def check_limits(db: sqlite3.Connection, conversation_id: int) -> None:
    since_hour = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    runs_last_hour = db.execute("SELECT COUNT(*) FROM runs WHERE created_at >= ?", (since_hour,)).fetchone()[0]
    if runs_last_hour >= config.MAX_RUNS_PER_HOUR:
        raise LimitReached(f"Hourly limit reached ({config.MAX_RUNS_PER_HOUR} analyses per hour). Try again later.")

    spent = spent_today(db)
    if spent >= config.DAILY_BUDGET_USD:
        raise LimitReached(f"Today's AI budget is used up (${spent:.4f} of ${config.DAILY_BUDGET_USD:.2f}).")

    done = db.execute("SELECT COUNT(*) FROM runs WHERE conversation_id = ? AND outcome = 'ok'",
                      (conversation_id,)).fetchone()[0]
    if done >= MAX_ANALYSES_PER_CONVERSATION:
        raise LimitReached(f"This conversation has already been analyzed {done} times, the limit.")


def spent_today(db: sqlite3.Connection) -> float:
    start = date.today().isoformat()
    return float(db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE created_at >= ?",
                            (start,)).fetchone()[0])


def cost_usd(input_tokens: int, cached_tokens: int, cache_write_tokens: int, output_tokens: int) -> float:
    """Price one run. Cached and cache-write tokens are part of input_tokens, so subtract them."""
    p = config.PRICE_PER_M
    fresh = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    return (fresh * p["input"] + cached_tokens * p["cached_input"]
            + cache_write_tokens * p["cache_write"] + output_tokens * p["output"]) / 1_000_000


# ---------- 2. Injection scan ----------

INJECTION_PATTERNS = [
    r"\bignore\b.{0,40}\b(instruction|rule|prompt|direction)s?\b",
    r"\bdisregard\b.{0,40}\b(instruction|rule|prompt|above|previous|prior)",
    r"\b(system|developer|admin)\s+(prompt|message|notice|override|instruction)",
    r"\byou are now\b",
    r"\bnew instructions?\b",
    r"\bact as\b.{0,30}\b(admin|system|developer|unrestricted)",
    r"\b(reveal|print|show|output)\b.{0,30}\b(system prompt|api key|password|secret|credentials?)\b",
    r"\b(note|message) to (the )?(ai|assistant|model|agent|llm)\b",
    r"\b(ai|assistant|agent|model)\s*[:,]\s*(please\s+)?(add|create|mark|delete|send|email|approve)\b",
    r"\bauto-?approve\b",
]
_injection_re = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def suspicious_sentences(notes: str) -> list[str]:
    return [s for s in split_sentences(notes) if any(r.search(s) for r in _injection_re)]


# ---------- 3. Proposal validator ----------

_QUOTE_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                            "–": "-", "—": "-", " ": " "})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTE_MAP)).strip().casefold()


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
URL_RE = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|net|org|io|ai|example|xyz|ru)/\S*", re.IGNORECASE)
PHONE_RE = re.compile(r"(\+\d{1,3}[\s.-]?)?\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
SECRET_RE = re.compile(r"\b(api[\s_-]?keys?|passwords?|secret keys?|access tokens?|ssn|social security number)\b",
                       re.IGNORECASE)
BULK_DATA_RE = re.compile(
    r"\b(send|forward|share|export|email|upload|post|copy)\b.{0,60}"
    r"\b(all|every|entire|full|whole|list of|each)\b.{0,40}"
    r"\b(contacts?|records?|database|notes|emails?|addresses|employers|data)\b",
    re.IGNORECASE)
BULK_EDIT_RE = re.compile(r"\b(delete|remove|erase|wipe|mark)\b.{0,30}\b(all|every|each)\b", re.IGNORECASE)

MAX_TEXT = {"task": 200, "contact_note": 400, "learning": 400, "new_question": 250,
            "answer_question": 500, "employer_note": 400}


@dataclass
class ValidationContext:
    notes: str
    employer_ids: set[int]
    open_question_ids: set[int]
    path_keys: set[str]
    today: date = field(default_factory=date.today)


@dataclass
class Verdict:
    accepted: list[dict]
    blocked: list[dict]        # {"kind", "text", "reason"}


def check_text(kind: str, text: str) -> str | None:
    """Content rules shared by AI proposals and by the user's own edits. Returns a reason or None."""
    if not text:
        return "empty text"
    if len(text) > MAX_TEXT.get(kind, 300):
        return f"text longer than {MAX_TEXT.get(kind, 300)} characters"
    if EMAIL_RE.search(text):
        return "contains an email address"
    if URL_RE.search(text):
        return "contains a web link"
    if PHONE_RE.search(text):
        return "contains a phone number"
    if SECRET_RE.search(text):
        return "mentions keys, passwords or other secrets"
    if BULK_DATA_RE.search(text):
        return "asks to send or share data in bulk"
    if BULK_EDIT_RE.search(text):
        return "asks for a bulk edit or deletion"
    return None


def _valid_due(due: str | None, today: date) -> tuple[bool, str]:
    if not due:
        return True, ""
    try:
        d = date.fromisoformat(due)
    except ValueError:
        return False, ""
    if d < today - timedelta(days=1) or d > today + timedelta(days=365):
        return False, ""
    return True, d.isoformat()


def validate_changes(changes: list[dict], ctx: ValidationContext) -> Verdict:
    accepted: list[dict] = []
    blocked: list[dict] = []
    notes_norm = normalize(ctx.notes)
    bad_sentences = [normalize(s) for s in suspicious_sentences(ctx.notes)]
    seen: set[tuple[str, str]] = set()

    def block(item: dict, reason: str) -> None:
        blocked.append({"kind": str(item.get("kind", ""))[:40], "text": str(item.get("text", ""))[:200],
                        "reason": reason})

    for item in changes:
        if len(accepted) >= config.MAX_PROPOSALS:
            block(item, f"more than {config.MAX_PROPOSALS} suggestions")
            continue
        kind = item.get("kind")
        text = str(item.get("text") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if kind not in ALLOWED_KINDS:
            block(item, f"change type '{kind}' is not allowed")
            continue
        reason = check_text(kind, text)
        if reason:
            block(item, reason)
            continue
        ev = normalize(evidence).strip(" .\"'")
        if len(ev) < 8:
            block(item, "no supporting quote from the notes")
            continue
        if ev not in notes_norm:
            block(item, "quote does not appear in the notes")
            continue
        if any(ev in s or s in ev for s in bad_sentences):
            block(item, "based on a sentence that tries to give the AI instructions")
            continue

        clean = {"kind": kind, "text": text, "evidence": evidence[:500],
                 "rationale": str(item.get("rationale") or "").strip()[:300]}
        employer_id = item.get("employer_id")
        if employer_id is not None:
            if employer_id not in ctx.employer_ids:
                block(item, "points at an employer that does not exist")
                continue
            clean["employer_id"] = employer_id
        path = item.get("path")
        if path is not None:
            if path not in ctx.path_keys:
                block(item, "unknown career path")
                continue
            clean["path"] = path
        if kind == "task":
            ok, due = _valid_due(item.get("due"), ctx.today)
            if not ok:
                block(item, "due date is invalid or out of range")
                continue
            clean["due"] = due
        if kind == "answer_question":
            qid = item.get("question_id")
            if qid not in ctx.open_question_ids:
                block(item, "points at a question that is not open")
                continue
            clean["question_id"] = qid
        if kind == "employer_note" and "employer_id" not in clean:
            block(item, "employer note without an employer")
            continue

        key = (kind, normalize(text))
        if key in seen:
            block(item, "duplicate suggestion")
            continue
        seen.add(key)
        accepted.append(clean)
    return Verdict(accepted, blocked)


def check_feature_limits(db: sqlite3.Connection, kind: str, per_day: int) -> None:
    """Shared limits for the one-shot agents (Path Finder, Target Scout, Connections)."""
    since_hour = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    if db.execute("SELECT COUNT(*) FROM runs WHERE created_at >= ?", (since_hour,)).fetchone()[0] >= config.MAX_RUNS_PER_HOUR:
        raise LimitReached("Hourly AI limit reached. Try again later.")
    spent = spent_today(db)
    if spent >= config.DAILY_BUDGET_USD:
        raise LimitReached(f"Today's AI budget is used up (${spent:.4f} of ${config.DAILY_BUDGET_USD:.2f}).")
    n = db.execute("SELECT COUNT(*) FROM runs WHERE kind = ? AND created_at >= ?",
                   (kind, date.today().isoformat())).fetchone()[0]
    if n >= per_day:
        raise LimitReached(f"You've used this {n} times today, the daily limit.")


def record_run(db: sqlite3.Connection, kind: str, res, total: int, blocked: list[dict]) -> int:
    u = res.usage
    cost = cost_usd(u["input_tokens"], u["cached_tokens"], u["cache_write_tokens"], u["output_tokens"])
    cur = db.execute(
        """INSERT INTO runs(created_at, kind, model, outcome, input_tokens, cached_tokens, cache_write_tokens,
               output_tokens, requests, tool_calls, cost_usd, latency_ms, proposals_total,
               blocked_by_validator, blocked_reasons, tools_used, error)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, '[]', ?)""",
        (datetime.now().isoformat(timespec="seconds"), kind, config.MODEL_NAME, res.outcome, u["input_tokens"],
         u["cached_tokens"], u["cache_write_tokens"], u["output_tokens"], u["requests"], u["tool_calls"], cost,
         res.latency_ms, total, len(blocked), json.dumps(blocked), res.error))
    return cur.lastrowid
