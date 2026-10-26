"""The user's profile: the multiple-choice "About you" questions, step 1 of setup.

The Path Finder uses them to suggest career directions, the Target Scout to suggest employers, and
the Connections agent to suggest people and force multipliers. Priorities, deal-breakers and tracks
are separate steps (decisions.py, tracks.py). Answers are stored as one JSON object in
settings['profile'] and validated against this list.
"""

from __future__ import annotations

import json
import sqlite3

from . import db


def _opts(*labels: str) -> list[dict]:
    return [{"key": l, "label": l} for l in labels]


SECTIONS = [
    {"key": "you", "title": "Where you are", "questions": [
        {"key": "stage", "label": "Career stage", "type": "single", "options": _opts(
            "Pre-MBA", "First-year MBA", "Second-year MBA", "Other graduate program", "Early career (0-5 years)",
            "Career switcher (5+ years)")},
        {"key": "looking_for", "label": "What are you looking for?", "type": "single", "options": _opts(
            "Summer internship", "Full-time role", "Both", "Just exploring")},
        {"key": "second_summer", "label": "Could you have a second internship summer (joint degree, extra year)?",
         "type": "single", "options": _opts("Yes", "Maybe", "No")},
        {"key": "background", "label": "Your background", "type": "multi", "options": _opts(
            "Military", "Consulting", "Finance", "Engineering / technical", "Operations", "Sales / BD",
            "Nonprofit / public sector", "Startup", "Other")},
    ]},
    {"key": "direction", "title": "The roles you want", "questions": [
        {"key": "industries", "label": "Industries you're curious about", "type": "multi", "options": _opts(
            "Not sure yet", "Energy & infrastructure", "Outdoor recreation", "Real estate & development",
            "Consulting", "Technology", "Finance / PE / VC", "Healthcare", "Climate & sustainability",
            "Public sector & policy", "Nonprofit & social impact", "Consumer & retail", "Manufacturing & industrials",
            "Sports & entertainment", "Education")},
        {"key": "functions", "label": "Which functions?", "type": "multi", "options": _opts(
            "Not sure yet", "Strategy", "Business development / commercial", "Project development", "Operations", "Product",
            "Finance & investing", "Marketing", "General management / chief of staff", "Policy & advocacy")},
        {"key": "company_stage", "label": "Company size and type", "type": "multi", "options": _opts(
            "Startup (<50)", "Growth (50-500)", "Large (500+)", "Government", "Nonprofit")},
        {"key": "mission", "label": "How much does the mission matter?", "type": "single", "options": _opts(
            "Must have", "Strong plus", "Nice to have", "Not a factor")},
    ]},
    {"key": "work", "title": "The work itself", "questions": [
        {"key": "energy", "label": "What kind of work energizes you? (up to 2)", "type": "multi", "max": 2,
         "options": _opts("Building projects", "Analysis & modeling", "Deal-making & negotiation",
                          "Leading people & operations", "Hands-on field work", "Advocacy & communication")},
        {"key": "ownership", "label": "Ownership", "type": "single", "options": _opts(
            "Own a project end to end", "Part of a strong team on big projects", "Rotate and learn broadly")},
        {"key": "team_size", "label": "Team size", "type": "single", "options": _opts(
            "Small (<10)", "Medium (10-50)", "Large (50+)", "No preference")},
        {"key": "travel", "label": "Travel", "type": "single", "options": _opts(
            "None", "Under 10%", "10-30%", "Over 30% is fine")},
        {"key": "field_office", "label": "Field vs. office", "type": "single", "options": _opts(
            "Mostly office", "Mixed", "Mostly in the field", "No preference")},
    ]},
    {"key": "life", "title": "Life and logistics", "questions": [
        {"key": "regions", "label": "Regions", "type": "multi", "options": _opts(
            "Mountain West", "Pacific Northwest", "California", "Northeast", "Mid-Atlantic", "Southeast",
            "Texas & South", "Midwest", "International", "Anywhere remote")},
        {"key": "setting", "label": "Setting", "type": "single", "options": _opts(
            "Big city", "Mid-size city", "Mountain or small town", "No preference")},
        {"key": "anchors", "label": "Lifestyle anchors", "type": "multi", "options": _opts(
            "Near skiing / mountains", "Near the ocean", "Near family", "Partner's job location", "Good schools", "None")},
        {"key": "arrangement", "label": "Work arrangement", "type": "single", "options": _opts(
            "In office", "Hybrid", "Remote", "No preference")},
        {"key": "hours", "label": "Weekly hours you'd accept, at most", "type": "single", "options": _opts(
            "Under 45", "45-55", "55-65", "65+")},
        {"key": "schedule", "label": "Schedule", "type": "single", "options": _opts(
            "Predictable", "Occasional crunch is fine", "Intense is fine")},
    ]},
    {"key": "money", "title": "Money", "questions": [
        {"key": "salary", "label": "Full-time base salary target", "type": "single", "options": _opts(
            "Under $100k", "$100-150k", "$150-200k", "$200k+")},
        {"key": "upside", "label": "Upside you prefer", "type": "single", "options": _opts(
            "Steady salary", "Bonus", "Equity", "Profit sharing", "No preference")},
        {"key": "trade_pay", "label": "Would you trade pay for mission or lifestyle?", "type": "single", "options": _opts(
            "Yes, significantly", "Somewhat", "No")},
    ]},
]
QUESTIONS = {q["key"]: q for s in SECTIONS for q in s["questions"]}
MAX_KNOWN_EMPLOYERS = 10


class ProfileError(ValueError):
    pass


def get(conn: sqlite3.Connection) -> dict:
    return json.loads(db.setting(conn, "profile", "{}"))


def is_complete(answers: dict) -> bool:
    return all(answers.get(k) for k in QUESTIONS)


def save(conn: sqlite3.Connection, answers: dict) -> dict:
    """Validate every answer against the question list, then store it. Every question is required,
    except the optional list of employers the user already has in mind."""
    clean: dict = {}
    for key, q in QUESTIONS.items():
        value = answers.get(key)
        allowed = {o["key"] for o in q["options"]}
        if q["type"] == "single":
            if value not in allowed:
                raise ProfileError(f"Answer \"{q['label']}\".")
            clean[key] = value
        else:
            if not isinstance(value, list) or not value:
                raise ProfileError(f"Pick at least one for \"{q['label']}\".")
            if set(value) - allowed:
                raise ProfileError(f"Unknown choice for \"{q['label']}\".")
            if q.get("max") and len(value) > q["max"]:
                raise ProfileError(f"Pick at most {q['max']} for \"{q['label']}\".")
            clean[key] = [o["key"] for o in q["options"] if o["key"] in value]   # keep the listed order
    known = answers.get("known_employers") or []
    if not isinstance(known, list):
        raise ProfileError("Known employers must be a list.")
    names = []
    for n in known:
        n = " ".join(str(n).split())[:80]
        if n and n.lower() not in {x.lower() for x in names}:
            names.append(n)
    if len(names) > MAX_KNOWN_EMPLOYERS:
        raise ProfileError(f"List at most {MAX_KNOWN_EMPLOYERS} employers you already have in mind.")
    clean["known_employers"] = names
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('profile', ?)", (json.dumps(clean),))
    return clean


def as_text(answers: dict) -> str:
    """The answers as plain lines for the agent prompt."""
    lines = []
    for s in SECTIONS:
        for q in s["questions"]:
            v = answers.get(q["key"])
            if v:
                lines.append(f"- {q['label']}: {', '.join(v) if isinstance(v, list) else v}")
    if answers.get("known_employers"):
        lines.append("- Employers already on their list: " + ", ".join(answers["known_employers"]))
    return "\n".join(lines)
