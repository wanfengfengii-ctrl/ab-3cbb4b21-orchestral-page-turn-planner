"""API-level tests: validation rules and response shape."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_PAYLOAD = {
    "pageCapacity": 10,
    "turnRequiredMs": 500,
    "measures": [
        {"height": 3, "restAfterMs": 1000},
        {"height": 3, "restAfterMs": 1000},
        {"height": 4, "restAfterMs": 1000},
        {"height": 3, "restAfterMs": 1000},
        {"height": 3, "restAfterMs": 1000},
    ],
}


def post_raw(body: bytes):
    return client.post(
        "/api/solve", content=body, headers={"Content-Type": "application/json"}
    )


def post_json(payload) -> "object":
    return post_raw(json.dumps(payload).encode())


def test_health() -> None:
    assert client.get("/api/health").status_code == 200


def test_known_solution() -> None:
    response = post_json(VALID_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["objective"] == {
        "pages": 2,
        "unsafeTurns": 0,
        "maxGapMs": 0,
        "sumSquaredSlack": 16,
    }
    assert data["turnPoints"] == [2]
    assert data["pageEndIndices"] == [2, 5]
    assert [p["endMeasure"] for p in data["pages"]] == [2, 5]
    assert data["pages"][0]["turn"] == {
        "restAfterMs": 1000,
        "requiredMs": 500,
        "safe": True,
        "gapMs": 0,
    }
    assert data["pages"][-1]["isLastPage"] is True
    assert data["pages"][-1]["turn"] is None


def _assert_422(response, expected_paths: list[str] | None = None) -> None:
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "validation failed"
    assert isinstance(body["errors"], list) and body["errors"]
    for error in body["errors"]:
        assert set(error) == {"path", "message"}
    if expected_paths is not None:
        assert [e["path"] for e in body["errors"]] == expected_paths


@pytest.mark.parametrize(
    "raw, expected_path",
    [
        (b'{"pageCapacity": 1.5, "turnRequiredMs": 0, "measures": [{"height": 1, "restAfterMs": 0}]}', "pageCapacity"),
        (b'{"pageCapacity": 1e3, "turnRequiredMs": 0, "measures": [{"height": 1, "restAfterMs": 0}]}', "pageCapacity"),
        (b'{"pageCapacity": 100, "turnRequiredMs": 0, "measures": [{"height": 1.0, "restAfterMs": 0}]}', "measures[0].height"),
        (b'{"pageCapacity": 100, "turnRequiredMs": 0, "measures": [{"height": "5", "restAfterMs": 0}]}', "measures[0].height"),
        (b'{"pageCapacity": 100, "turnRequiredMs": 0, "measures": [{"height": true, "restAfterMs": 0}]}', "measures[0].height"),
        (b'{"pageCapacity": 100, "turnRequiredMs": 0, "measures": [{"height": null, "restAfterMs": 0}]}', "measures[0].height"),
        (b'{"pageCapacity": 100, "turnRequiredMs": 0, "measures": [{"height": -5, "restAfterMs": 0}]}', "measures[0].height"),
        (b'{"pageCapacity": 100, "turnRequiredMs": 0, "measures": [{"height": 1, "restAfterMs": NaN}]}', "measures[0].restAfterMs"),
    ],
)
def test_rejects_non_conforming_tokens(raw: bytes, expected_path: str) -> None:
    response = post_raw(raw)
    _assert_422(response, [expected_path])


def test_rejects_leading_zero_token() -> None:
    # `01` is not even valid JSON, so the whole body is rejected with 422.
    response = post_raw(
        b'{"pageCapacity": 01, "turnRequiredMs": 0, "measures": [{"height": 1, "restAfterMs": 0}]}'
    )
    _assert_422(response, ["$"])


@pytest.mark.parametrize(
    "patch, expected_path",
    [
        ({"pageCapacity": 0}, "pageCapacity"),
        ({"pageCapacity": 30001}, "pageCapacity"),
        ({"turnRequiredMs": 30001}, "turnRequiredMs"),
    ],
)
def test_range_violations(patch: dict, expected_path: str) -> None:
    payload = {**VALID_PAYLOAD, **patch}
    _assert_422(post_json(payload), [expected_path])


def test_measure_range_and_capacity_violations() -> None:
    payload = {
        "pageCapacity": 10,
        "turnRequiredMs": 0,
        "measures": [
            {"height": 0, "restAfterMs": 0},
            {"height": 30001, "restAfterMs": 0},
            {"height": 11, "restAfterMs": 0},
            {"height": 5, "restAfterMs": 30001},
        ],
    }
    _assert_422(
        post_json(payload),
        [
            "measures[0].height",
            "measures[1].height",
            "measures[2].height",
            "measures[3].restAfterMs",
        ],
    )


def test_measure_count_bounds() -> None:
    _assert_422(post_json({**VALID_PAYLOAD, "measures": []}), ["measures"])
    too_many = [{"height": 1, "restAfterMs": 0}] * 501
    _assert_422(post_json({**VALID_PAYLOAD, "measures": too_many}), ["measures"])


def test_errors_are_collected_in_input_position_order() -> None:
    payload = {
        "pageCapacity": 0,
        "turnRequiredMs": 500,
        "measures": [
            {"height": 10, "restAfterMs": 30001},
            {"height": 10, "restAfterMs": 10},
            {"height": "x", "restAfterMs": 10},
        ],
    }
    _assert_422(
        post_json(payload),
        ["pageCapacity", "measures[0].restAfterMs", "measures[2].height"],
    )


def test_missing_fields() -> None:
    _assert_422(post_json({}), ["pageCapacity", "turnRequiredMs", "measures"])
    _assert_422(
        post_json({"pageCapacity": 10, "turnRequiredMs": 0, "measures": [{}]}),
        ["measures[0].height", "measures[0].restAfterMs"],
    )
