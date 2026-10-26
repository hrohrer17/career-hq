"""Priorities, deal-breakers and the Decision Studio's weighted match."""

import pytest

from app import agent, db, decisions

RANKING = ["work", "pay", "lifestyle", "impact", "team", "growth", "stability", "brand"]


def _emp(conn, name):
    return db.one(conn, "SELECT id FROM employers WHERE name LIKE ?", (name + "%",))["id"]


def test_match_math():
    w = {"a": 50, "b": 30, "c": 20}
    assert decisions.match({}, w) == {"score": None, "coverage": 0}
    assert decisions.match({"a": 5, "b": 5, "c": 5}, w) == {"score": 100, "coverage": 100}
    assert decisions.match({"a": 1, "b": 1, "c": 1}, w) == {"score": 0, "coverage": 100}
    assert decisions.match({"a": 3}, w) == {"score": 50, "coverage": 50}
    # Weighted: a=5 (50), b=1 (30) -> avg (250+30)/80 = 3.5 -> 62.5 -> 62 (banker's rounding) ; coverage 80
    assert decisions.match({"a": 5, "b": 1}, w) == {"score": round((3.5 - 1) / 4 * 100), "coverage": 80}
    assert decisions.match({"a": 5}, {"a": 0, "b": 10}) == {"score": None, "coverage": 0}


def test_demo_ranking_and_ruled_out(client):
    d = client.get("/api/decisions").json()
    names = [r["name"] for r in d["ranked"]]
    assert names[0] == "Ridgeline Geothermal" and [r["rank"] for r in d["ranked"]] == list(range(1, len(names) + 1))
    assert [r["score"] for r in d["ranked"]] == sorted((r["score"] for r in d["ranked"]), reverse=True)
    assert [r["name"] for r in d["ruled_out"]] == ["High Desert Transmission"]
    assert [r["name"] for r in d["unscored"]] == ["Alpine Commons Land Trust"]
    ridgeline = d["ranked"][0]
    assert ridgeline["biggest_unknown"]["key"] == "stability"         # highest-weight criterion not scored
    assert ridgeline["scores"]["work"]["note"].startswith("Interns own")


def test_weights_change_the_ranking(client):
    # Make pay all that matters: Basecamp (pay 2) must fall below Cascade (pay 4).
    for k in RANKING:
        client.patch(f"/api/criteria/{k}", json={"weight": 40 if k == "pay" else 0})
    ranked = [r["name"] for r in client.get("/api/decisions").json()["ranked"]]
    assert ranked.index("Cascade Solar Development") < ranked.index("Basecamp Recreation Partners")
    client.post("/api/criteria/reset")
    crit = client.get("/api/priorities").json()["criteria"]
    assert [c["weight"] for c in crit] == decisions.RANK_WEIGHTS
    assert round(sum(c["share"] for c in crit)) == 100


def test_scores_validation_and_clearing(client):
    with db.connect() as conn:
        alpine = _emp(conn, "Alpine")
    assert client.put(f"/api/employers/{alpine}/scores/work", json={"score": 6}).status_code == 422
    assert client.put(f"/api/employers/{alpine}/scores/vibes", json={"score": 3}).status_code == 422
    assert client.put(f"/api/employers/{alpine}/scores/work", json={"score": 4, "note": "Land deals"}).status_code == 200
    d = client.get("/api/decisions").json()
    assert "Alpine Commons Land Trust" in [r["name"] for r in d["ranked"]]
    client.put(f"/api/employers/{alpine}/scores/work", json={"score": None})
    assert "Alpine Commons Land Trust" in [r["name"] for r in client.get("/api/decisions").json()["unscored"]]


def test_dealbreakers_rule_out_and_must_be_the_users_own(client):
    with db.connect() as conn:
        ridge = _emp(conn, "Ridgeline")
    assert client.put(f"/api/employers/{ridge}/dealbreakers", json={"keys": ["defense"]}).status_code == 422
    assert client.put(f"/api/employers/{ridge}/dealbreakers", json={"keys": ["over_60_hours"]}).status_code == 200
    d = client.get("/api/decisions").json()
    assert "Ridgeline Geothermal" in [r["name"] for r in d["ruled_out"]]
    # Dropping that deal-breaker in setup clears the hit, and Ridgeline is ranked again.
    client.put("/api/priorities", json={"ranking": RANKING, "dealbreakers": ["heavy_travel"]})
    assert "Ridgeline Geothermal" in [r["name"] for r in client.get("/api/decisions").json()["ranked"]]


@pytest.mark.parametrize("body", [
    {"ranking": RANKING[:7], "dealbreakers": []},
    {"ranking": RANKING[:7] + ["work"], "dealbreakers": []},
    {"ranking": RANKING, "dealbreakers": ["mondays"]},
])
def test_bad_priorities_are_refused(client, body):
    assert client.put("/api/priorities", json=body).status_code == 422


def test_new_ranking_resets_weights_and_reaches_the_agent(client):
    new = ["impact", "lifestyle", "work", "pay", "team", "growth", "stability", "brand"]
    client.put("/api/priorities", json={"ranking": new, "dealbreakers": []})
    crit = client.get("/api/priorities").json()["criteria"]
    assert [c["key"] for c in crit] == new and crit[0]["weight"] == 25
    text = agent.user_profile_text()
    assert "1. Mission & impact [25%]" in text and "Deal-breakers: none" in text
