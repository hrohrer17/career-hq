"""Profile questions, the Target Scout (with a fake model), reactions, the top 10 and adding to Career HQ."""

import json

import pytest
from pydantic_ai.models.test import TestModel

from app import config, db, decisions, profile, scout

CRIT = decisions.CRITERIA_KEYS


def cand(name, track="energy", score=4, **kw):
    base = {"name": name, "track": track, "sub_sector": "Solar developer", "hq": "Denver, CO",
            "other_locations": "None known", "remote_policy": "Hybrid", "size": "Growth (50-500)",
            "ownership": "Private", "mba_roles": "Development associate", "kind_of_work": "Siting and deals",
            "typical_hours": "45-55", "schedule": "Occasional crunch", "travel": "10-30%",
            "field_office": "Mixed", "intern_pay": "$40-50/hr", "base_pay": "$150-170k", "upside": "Bonus",
            "hires_mba_interns": "Yes", "recruiting_path": "Off-cycle networking", "mission": "Clean power",
            "why_fit": "Fits the development track.", "fit": [{"criterion": k, "score": score, "reason": "r"} for k in CRIT],
            "dealbreaker_risks": [], "confidence": "Medium", "from_user_list": False}
    base.update(kw)
    return base


def fake_output(cands):
    return TestModel(call_tools=[], custom_output_args={"candidates": cands})


def suggest_with(client, cands):
    with scout.build_agent().override(model=fake_output(cands)):
        return client.post("/api/targets/suggest").json()


def test_demo_profile_passes_validation():
    with db.connect() as conn:
        saved = profile.save(conn, profile.get(conn))
    assert profile.is_complete(saved)


@pytest.mark.parametrize("change, message", [
    ({"stage": "Astronaut"}, "Career stage"),
    ({"regions": []}, "Regions"),
    ({"energy": ["Building projects", "Analysis & modeling", "Hands-on field work"]}, "at most 2"),
    ({"known_employers": [f"Co {i}" for i in range(11)]}, "at most 10"),
])
def test_profile_validation(client, change, message):
    answers = client.get("/api/profile").json()["answers"]
    r = client.put("/api/profile", json={**answers, **change})
    assert r.status_code == 422 and message in r.json()["detail"]


def test_scout_needs_a_complete_profile(client):
    with db.connect() as conn:
        conn.execute("DELETE FROM settings WHERE key = 'profile'")
    assert client.post("/api/targets/suggest").status_code == 409


def test_suggestions_are_validated(client):
    r = suggest_with(client, [
        cand("Bright Mesa Solar"),
        cand("Ridgeline Geothermal"),                                  # already an employer
        cand("Bright Mesa Solar", track="outdoor"),                     # duplicate in the same batch
        cand("Nowhere Co", track="sports"),                             # not one of the user's tracks
        cand("Sketchy Co", why_fit="Email hr@sketchy.example to apply."),
        cand("Long Hours LLC", typical_hours="65+", remote_policy="In office"),
    ])
    assert r["outcome"] == "ok" and r["added"] == 2
    reasons = sorted(b["reason"] for b in r["blocked"])
    assert reasons == ["already in Career HQ or already suggested", "already in Career HQ or already suggested",
                       "unknown track 'sports'", "why fit: contains an email address"]
    b = client.get("/api/targets").json()
    long_hours = next(c for c in b["candidates"] if c["name"] == "Long Hours LLC")
    # Implied by the parameters even though the model listed no risks; the user has over_60_hours.
    assert set(long_hours["risks"]) == {"over_60_hours", "fully_in_office"}
    assert [h["key"] for h in long_hours["dealbreakers_hit"]] == ["over_60_hours"]
    run = client.get("/api/usage").json()["runs"][0]
    assert run["kind"] == "scout" and run["blocked_by_validator"] == 4


def test_reactions_build_the_top_10_with_the_users_weights(client):
    names = [f"Employer {i:02d}" for i in range(14)]
    cands = [cand(n, score=1 + i % 5) for i, n in enumerate(names)]
    cands.append(cand("Too Far Travel", score=5, travel="Over 30%"))       # deal-breaker: heavy travel
    suggest_with(client, cands)
    b = client.get("/api/targets").json()
    ids = {c["name"]: c["id"] for c in b["candidates"]}
    assert b["top"] == []                                                  # nothing rated yet
    for i, n in enumerate(names):
        client.put(f"/api/targets/{ids[n]}/reaction", json={"reaction": ["interested", "maybe", "no"][i % 3]})
    client.put(f"/api/targets/{ids['Too Far Travel']}/reaction", json={"reaction": "interested"})
    b = client.get("/api/targets").json()
    top = b["top"]
    assert "Too Far Travel" not in [c["name"] for c in top]
    assert all(c["reaction"] in ("interested", "maybe") for c in top)
    assert len(top) == sum(1 for i in range(14) if i % 3 != 2)            # 10 eligible here
    assert [c["score"] for c in top] == sorted((c["score"] for c in top), reverse=True)
    assert client.put(f"/api/targets/{ids[names[0]]}/reaction", json={"reaction": "love"}).status_code == 422


def test_add_top_creates_employers_with_ai_estimate_labels(client):
    suggest_with(client, [cand("Bright Mesa Solar", score=5), cand("Quiet Pines Trust", track="outdoor", score=3)])
    b = client.get("/api/targets").json()
    for c in b["candidates"]:
        client.put(f"/api/targets/{c['id']}/reaction", json={"reaction": "interested"})
    added = client.post("/api/targets/add-top").json()["added"]
    assert sorted(added) == ["Bright Mesa Solar", "Quiet Pines Trust"]
    assert client.post("/api/targets/add-top").json()["added"] == []       # not added twice
    with db.connect() as conn:
        e = db.one(conn, "SELECT * FROM employers WHERE name = 'Bright Mesa Solar'")
        scores = db.rows(conn, "SELECT criterion, score, note FROM employer_scores WHERE employer_id = ?", (e["id"],))
    prof = json.loads(e["profile"])
    assert e["track"] == "energy" and e["location"] == "Denver, CO" and prof["verified"] is False
    assert prof["typical_hours"] == "45-55" and prof["source"].startswith("AI estimate")
    assert len(scores) == 8 and all(s["note"].startswith("AI estimate") for s in scores)
    ranked = {r["name"]: r for r in client.get("/api/decisions").json()["ranked"]}
    assert ranked["Bright Mesa Solar"]["ai_estimated"] == 8                 # in Decision Studio, labeled
    assert ranked["Ridgeline Geothermal"]["ai_estimated"] == 0


def test_scout_daily_cap(client, monkeypatch):
    monkeypatch.setattr(scout, "SCOUT_RUNS_PER_DAY", 1)
    suggest_with(client, [cand("One Co")])
    r = client.post("/api/targets/suggest")
    assert r.status_code == 429 and "daily limit" in r.json()["detail"]


def test_scout_prompt_has_the_users_context():
    text = scout.context_text()
    assert "Track keys to use: outdoor = Outdoor recreation, energy = Energy & infrastructure" in text
    assert "Career stage: First-year MBA" in text and "Ridgeline Geothermal" in text


def test_track_names_are_mapped_to_keys(client):
    """A model may answer with the track's name or short label instead of its key."""
    r = suggest_with(client, [cand("Name Co", track="Energy & infrastructure"), cand("Short Co", track="outdoor "),
                              cand("Label Co", track="Outdoor")])
    assert r["added"] == 3 and r["blocked"] == []
    tracks_by_name = {c["name"]: c["track"] for c in client.get("/api/targets").json()["candidates"]}
    assert tracks_by_name == {"Name Co": "energy", "Short Co": "outdoor", "Label Co": "outdoor"}
