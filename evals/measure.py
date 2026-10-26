"""Measure real token use, cost and latency for all four agents (for the report's Tokenomics section).

Runs on a throwaway copy of the sample data with the gateway cache bypassed, so every number is a
fresh model call. About $0.02 per full run.

  4 x Networking Debrief (four different real notes from the sample)
  3 x Path Finder
  2 x Target Scout (the second run must avoid the first run's employers)
  2 x Connections

Also records one full Debrief trace (every model request and tool call, in order) and how complete
the Target Scout's employer profiles are (share of fields it answered "Unknown").

Usage (from the repo folder):  python evals/measure.py
Writes evals/results/measure-<timestamp>.json and prints a summary.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["CAREER_HQ_DB"] = str(Path(tempfile.mkdtemp()) / "measure.sqlite3")
os.environ["CAREER_HQ_DAILY_BUDGET_USD"] = "0.20"
os.environ["CAREER_HQ_MAX_RUNS_PER_HOUR"] = "60"
os.environ["CAREER_HQ_BYPASS_GATEWAY_CACHE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from pydantic_ai import capture_run_messages  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

FIELDS = ["input_tokens", "cached_tokens", "output_tokens", "cost_usd", "latency_ms", "requests", "tool_calls"]


def summarize(runs: list[dict]) -> dict:
    out = {"n": len(runs)}
    for f in FIELDS:
        vals = [r[f] for r in runs]
        out[f] = {"mean": round(statistics.mean(vals), 6), "min": min(vals), "max": max(vals)}
    return out


def trace_from(messages) -> list[dict]:
    steps = []
    for m in messages:
        for p in getattr(m, "parts", []):
            kind = type(p).__name__
            if kind == "ToolCallPart":
                steps.append({"step": "tool call", "tool": p.tool_name, "args": p.args if isinstance(p.args, dict) else str(p.args)})
            elif kind == "ToolReturnPart":
                content = p.content
                text = json.dumps(content, default=str) if not isinstance(content, str) else content
                steps.append({"step": "tool result", "tool": p.tool_name, "chars": len(text), "preview": text[:160]})
            elif kind == "UserPromptPart":
                steps.append({"step": "user message", "chars": len(str(p.content))})
        if type(m).__name__ == "ModelResponse" and getattr(m, "usage", None):
            u = m.usage
            steps.append({"step": "model response", "input_tokens": u.input_tokens, "cached_tokens": u.cache_read_tokens,
                          "output_tokens": u.output_tokens})
    return steps


def main() -> None:
    db.init_db(with_sample=True)
    c = TestClient(app)
    ids = {x["name"]: x["id"] for x in c.get("/api/contacts").json()}

    # Networking Debrief: Priya and Sam sample notes (new conversations), Marcus and Elena (seeded ones).
    trace = None
    for name in ("Priya Raman", "Sam Okafor"):
        notes = c.get(f"/api/contacts/{ids[name]}/sample-notes").json()["notes"]
        conv = c.post(f"/api/contacts/{ids[name]}/conversations", json={"notes": notes}).json()["id"]
        if trace is None:
            with capture_run_messages() as msgs:
                c.post(f"/api/conversations/{conv}/analyze")
            trace = trace_from(msgs)
        else:
            c.post(f"/api/conversations/{conv}/analyze")
    for name in ("Marcus Hale", "Elena Vasquez"):
        conv = c.get(f"/api/contacts/{ids[name]}").json()["conversations"][0]["id"]
        c.post(f"/api/conversations/{conv}/analyze")

    for _ in range(3):
        c.post("/api/directions/suggest")
    for _ in range(2):
        c.post("/api/targets/suggest")
    for _ in range(2):
        c.post("/api/connections/suggest")

    runs = c.get("/api/usage").json()["runs"]
    by_kind: dict[str, list[dict]] = {}
    for r in runs:
        if r["outcome"] == "ok":
            by_kind.setdefault(r["kind"], []).append(r)
    failed = [{"kind": r["kind"], "outcome": r["outcome"], "error": r["error"]} for r in runs if r["outcome"] != "ok"]

    # How complete are the Target Scout's employer profiles?
    cands = c.get("/api/targets").json()["candidates"]
    param_keys = [k for k in cands[0]["params"]] if cands else []
    unknown = {k: sum(1 for x in cands if str(x["params"].get(k, "")).strip().lower().startswith("unknown")) for k in param_keys}
    total_fields = len(cands) * len(param_keys)

    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"), "model": "gpt-6-luna",
        "summary": {k: summarize(v) for k, v in by_kind.items()},
        "runs": [{k: r[k] for k in ("kind", "contact", *FIELDS, "proposals_total", "blocked_by_validator")} for r in runs],
        "failed": failed,
        "scout_completeness": {"candidates": len(cands), "fields_per_candidate": len(param_keys),
                               "unknown_share": round(sum(unknown.values()) / total_fields, 3) if total_fields else None,
                               "unknown_by_field": unknown},
        "debrief_trace": trace,
        "total_cost_usd": round(sum(r["cost_usd"] for r in runs), 6),
    }
    out = REPO / "evals" / "results" / f"measure-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    for kind, s in result["summary"].items():
        print(f"{kind:12s} n={s['n']}  in={s['input_tokens']['mean']:.0f} (cached {s['cached_tokens']['mean']:.0f})  "
              f"out={s['output_tokens']['mean']:.0f}  ${s['cost_usd']['mean']:.5f}  {s['latency_ms']['mean'] / 1000:.1f}s  "
              f"requests={s['requests']['mean']:.1f} tools={s['tool_calls']['mean']:.1f}")
    print("failed:", failed)
    print("scout unknown share:", result["scout_completeness"]["unknown_share"])
    print(f"total ${result['total_cost_usd']:.5f} -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
