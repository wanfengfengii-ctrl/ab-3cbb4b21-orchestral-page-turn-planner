"""FastAPI entrypoint for the orchestra pagination service."""
from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .solver import build_response
from .validation import FieldError, parse_body, validate_payload

app = FastAPI(title="Orchestra Page-Turn Planner", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _unprocessable(errors: list[FieldError]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "validation failed",
            "errors": [error.as_dict() for error in errors],
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/solve")
async def solve(request: Request) -> Response:
    raw = await request.body()
    data, parse_error = parse_body(raw)
    if parse_error is not None:
        return _unprocessable([parse_error])

    validated, errors = validate_payload(data)
    if errors:
        return _unprocessable(errors)
    assert validated is not None

    return JSONResponse(
        content=build_response(
            heights=validated.heights,
            rests=validated.rests,
            capacity=validated.page_capacity,
            turn_required_ms=validated.turn_required_ms,
        )
    )
