"""FastAPI entrypoint for the page-turn planner."""
from __future__ import annotations

from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .planner import solve
from .validation import Issue, decode_body, validate

app = FastAPI(title="Page-Turn Planner", version="1.0.0")

# The web container proxies /api, but permissive CORS keeps local development
# (vite dev server on another port) hassle-free.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/plan")
async def create_plan(request: Request) -> object:
    raw = await request.body()
    doc, error = decode_body(raw)
    if error is not None:
        return _unprocessable([error])
    parsed, issues = validate(doc)
    if issues:
        return _unprocessable(issues)

    assert parsed is not None
    plan = solve(parsed.measures, parsed.page_capacity, parsed.turn_required_ms)
    return {
        "pageCapacity": parsed.page_capacity,
        "turnRequiredMs": parsed.turn_required_ms,
        "objective": {
            "pages": plan.objective.pages,
            "unsafeTurns": plan.objective.unsafe_turns,
            "maxGapMs": plan.objective.max_gap_ms,
            "slackSquares": plan.objective.slack_squares,
        },
        "breaks": list(plan.breaks),
        "pages": [
            {
                "index": page.index,
                "start": page.start,
                "end": page.end,
                "heightSum": page.height_sum,
                "remaining": page.remaining,
                "turn": None
                if page.turn is None
                else {
                    "safe": page.turn.safe,
                    "restAfterMs": page.turn.rest_after_ms,
                    "gapMs": page.turn.gap_ms,
                },
            }
            for page in plan.pages
        ],
    }


def _unprocessable(issues: List[Issue]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"errors": [{"path": i.path, "message": i.message} for i in issues]},
    )
