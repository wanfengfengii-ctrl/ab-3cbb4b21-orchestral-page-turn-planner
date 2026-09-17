"""One-shot end-to-end verification for the orchestra page-turn planner.

Runs against a live stack (see docker-compose.yml): it exercises the API's
optimizer against exhaustive enumeration, checks every validation rule, and
confirms the web service serves the frontend and proxies the API.

Environment:
    API_URL  base URL of the API service   (default http://api:8000)
    WEB_URL  base URL of the web service   (default http://web; empty skips)
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

import httpx

API_URL = os.environ.get("API_URL", "http://api:8000").rstrip("/")
WEB_URL = os.environ.get("WEB_URL", "http://web").rstrip("/")

PASSES = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSES
    if condition:
        PASSES += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" -- {detail}" if detail else ""))


def wait_for_api() -> None:
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if httpx.get(f"{API_URL}/api/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise SystemExit("API did not become healthy within 120s")


def post_raw(body: bytes) -> httpx.Response:
    return httpx.post(
        f"{API_URL}/api/solve",
        content=body,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )


def post_json(payload) -> httpx.Response:
    return post_raw(json.dumps(payload).encode())


# --------------------------------------------------------------------------
# Optimizer correctness
# --------------------------------------------------------------------------

def brute_force(heights, rests, capacity, turn_required):
    """Exhaustively enumerate all compositions; return the best vector."""
    n = len(heights)
    best = None

    def rec(start, ends):
        nonlocal best
        if start == n:
            pages = len(ends)
            unsafe = max_gap = sum_sq = 0
            turn_points = []
            prev = 0
            for k, end in enumerate(ends):
                used = sum(heights[prev : end + 1])
                sum_sq += (capacity - used) ** 2
                if k < pages - 1:
                    turn_points.append(end + 1)
                    rest = rests[end]
                    if rest < turn_required:
                        unsafe += 1
                        max_gap = max(max_gap, turn_required - rest)
                prev = end + 1
            vector = (pages, unsafe, max_gap, sum_sq, turn_points)
            if best is None or vector < best:
                best = vector
            return
        used = 0
        for end in range(start, n):
            used += heights[end]
            if used > capacity:
                break
            rec(end + 1, ends + [end])

    rec(0, [])
    return best


def check_solution_shape(payload, data) -> bool:
    """Structural invariants every 200 response must satisfy."""
    try:
        measures = payload["measures"]
        capacity = payload["pageCapacity"]
        turn_required = payload["turnRequiredMs"]
        n = len(measures)
        objective = data["objective"]
        pages = data["pages"]

        if objective["pages"] != len(pages):
            return False
        if pages[0]["startMeasure"] != 1 or pages[-1]["endMeasure"] != n:
            return False
        for current, nxt in zip(pages, pages[1:]):
            if nxt["startMeasure"] != current["endMeasure"] + 1:
                return False
        for idx, page in enumerate(pages, 1):
            segment = measures[page["startMeasure"] - 1 : page["endMeasure"]]
            used = sum(m["height"] for m in segment)
            if page["page"] != idx or page["measureCount"] != len(segment):
                return False
            if page["usedHeight"] != used or used > capacity:
                return False
            if page["remainingCapacity"] != capacity - used:
                return False
        for page in pages[:-1]:
            rest = measures[page["endMeasure"] - 1]["restAfterMs"]
            turn = page["turn"]
            if page["isLastPage"] or turn is None:
                return False
            if turn["restAfterMs"] != rest or turn["requiredMs"] != turn_required:
                return False
            if turn["safe"] != (rest >= turn_required):
                return False
            if turn["gapMs"] != max(0, turn_required - rest):
                return False
        last = pages[-1]
        if not last["isLastPage"] or last["turn"] is not None:
            return False
        if data["turnPoints"] != [p["endMeasure"] for p in pages[:-1]]:
            return False
        if data["pageEndIndices"] != [p["endMeasure"] for p in pages]:
            return False
        return True
    except (KeyError, IndexError, TypeError):
        return False


def objective_of(data):
    o = data["objective"]
    return (o["pages"], o["unsafeTurns"], o["maxGapMs"], o["sumSquaredSlack"],
            data["turnPoints"])


def test_known_examples() -> None:
    print("known examples")
    # Lexicographic tie on the first four components: turn points [2] win.
    resp = post_json({
        "pageCapacity": 10,
        "turnRequiredMs": 500,
        "measures": [{"height": h, "restAfterMs": 1000} for h in (3, 3, 4, 3, 3)],
    })
    ok = resp.status_code == 200 and objective_of(resp.json()) == (2, 0, 0, 16, [2])
    check("tie broken by lexicographically smallest turn points", ok,
          resp.text[:300])

    # Forced unsafe turn: gap and slack must be exact.
    resp = post_json({
        "pageCapacity": 10,
        "turnRequiredMs": 1000,
        "measures": [
            {"height": 6, "restAfterMs": 100},
            {"height": 6, "restAfterMs": 0},
        ],
    })
    ok = resp.status_code == 200 and objective_of(resp.json()) == (2, 1, 900, 32, [1])
    check("unsafe turn reports gap 900 and slack^2 32", ok, resp.text[:300])

    # Single page: no turn at all, everything turn-related is zero.
    resp = post_json({
        "pageCapacity": 10,
        "turnRequiredMs": 30000,
        "measures": [{"height": 5, "restAfterMs": 0}, {"height": 5, "restAfterMs": 0}],
    })
    ok = resp.status_code == 200 and objective_of(resp.json()) == (1, 0, 0, 0, [])
    check("last page excluded from safety and gap stats", ok, resp.text[:300])

    # Max gap is minimised before slack^2: both 2-page splits tie on 16.
    resp = post_json({
        "pageCapacity": 8,
        "turnRequiredMs": 1000,
        "measures": [
            {"height": 4, "restAfterMs": 100},
            {"height": 4, "restAfterMs": 200},
            {"height": 4, "restAfterMs": 0},
        ],
    })
    ok = resp.status_code == 200 and objective_of(resp.json()) == (2, 1, 800, 16, [2])
    check("max gap minimised before slack^2", ok, resp.text[:300])


def test_against_brute_force(rounds: int = 60) -> None:
    print("random instances vs brute force")
    rng = random.Random(20260917)
    for case in range(rounds):
        n = rng.randint(1, 9)
        capacity = rng.randint(4, 18)
        heights = [rng.randint(1, capacity) for _ in range(n)]
        rests = [rng.randint(0, 1000) for _ in range(n)]
        turn_required = rng.choice([0, 1, 250, 500, 1000])
        payload = {
            "pageCapacity": capacity,
            "turnRequiredMs": turn_required,
            "measures": [
                {"height": h, "restAfterMs": r} for h, r in zip(heights, rests)
            ],
        }
        resp = post_json(payload)
        if resp.status_code != 200:
            check(f"random case {case}: status 200", False, resp.text[:300])
            continue
        data = resp.json()
        expected = brute_force(heights, rests, capacity, turn_required)
        got = objective_of(data)
        check(
            f"random case {case}: objective vector",
            tuple(got[:4]) == expected[:4] and got[4] == expected[4],
            f"expected {expected}, got {got}, payload={payload}",
        )
        check(f"random case {case}: response shape",
              check_solution_shape(payload, data))


def test_large_instance() -> None:
    print("500-measure instance")
    rng = random.Random(99)
    payload = {
        "pageCapacity": 30000,
        "turnRequiredMs": 15000,
        "measures": [
            {"height": rng.randint(1, 30000), "restAfterMs": rng.randint(0, 30000)}
            for _ in range(500)
        ],
    }
    started = time.time()
    resp = post_json(payload)
    elapsed = time.time() - started
    ok = resp.status_code == 200 and check_solution_shape(payload, resp.json())
    check("500 measures solved and well-formed", ok and elapsed < 10,
          f"status={resp.status_code} elapsed={elapsed:.2f}s")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def expect_422(name: str, body: bytes, expected_paths: list[str] | None = None) -> None:
    resp = post_raw(body)
    if resp.status_code != 422:
        check(name, False, f"status={resp.status_code} body={resp.text[:200]}")
        return
    try:
        data = resp.json()
        errors = data["errors"]
        paths = [e["path"] for e in errors]
        ok = (
            isinstance(errors, list)
            and len(errors) > 0
            and all(set(e) == {"path", "message"} for e in errors)
        )
        if expected_paths is not None:
            ok = ok and paths == expected_paths
        check(name, ok, f"paths={paths}")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        check(name, False, f"bad 422 body: {exc}")


def test_validation() -> None:
    print("validation rules")
    base = {"pageCapacity": 100, "turnRequiredMs": 10,
            "measures": [{"height": 5, "restAfterMs": 0}]}

    def variant(**kwargs):
        payload = json.loads(json.dumps(base))
        for key, value in kwargs.items():
            if key == "measure":
                payload["measures"][0].update(value)
            else:
                payload[key] = value
        return json.dumps(payload).encode()

    expect_422("decimal rejected", variant(measure={"height": 1.5}),
               ["measures[0].height"])
    expect_422("exponent rejected",
               b'{"pageCapacity": 1e3, "turnRequiredMs": 0, "measures": [{"height": 1, "restAfterMs": 0}]}',
               ["pageCapacity"])
    expect_422("string rejected", variant(measure={"height": "5"}),
               ["measures[0].height"])
    expect_422("boolean rejected", variant(measure={"restAfterMs": True}),
               ["measures[0].restAfterMs"])
    expect_422("null rejected", variant(measure={"height": None}),
               ["measures[0].height"])
    expect_422("negative rejected", variant(measure={"restAfterMs": -1}),
               ["measures[0].restAfterMs"])
    expect_422("leading zero rejected",
               b'{"pageCapacity": 01, "turnRequiredMs": 0, "measures": [{"height": 1, "restAfterMs": 0}]}',
               ["$"])
    expect_422("NaN rejected",
               b'{"pageCapacity": 100, "turnRequiredMs": 0, "measures": [{"height": 1, "restAfterMs": NaN}]}',
               ["measures[0].restAfterMs"])

    expect_422("height below range", variant(measure={"height": 0}),
               ["measures[0].height"])
    expect_422("height above range", variant(measure={"height": 30001}),
               ["measures[0].height"])
    expect_422("capacity below range", variant(pageCapacity=0), ["pageCapacity"])
    expect_422("capacity above range", variant(pageCapacity=30001), ["pageCapacity"])
    expect_422("turnRequiredMs above range", variant(turnRequiredMs=30001),
               ["turnRequiredMs"])
    expect_422("restAfterMs above range", variant(measure={"restAfterMs": 30001}),
               ["measures[0].restAfterMs"])
    expect_422("height exceeds capacity",
               json.dumps({"pageCapacity": 10, "turnRequiredMs": 0,
                           "measures": [{"height": 11, "restAfterMs": 0}]}).encode(),
               ["measures[0].height"])

    expect_422("zero measures", json.dumps({**base, "measures": []}).encode(),
               ["measures"])
    expect_422("501 measures",
               json.dumps({**base,
                           "measures": [{"height": 1, "restAfterMs": 0}] * 501}).encode(),
               ["measures"])
    expect_422("missing fields", b"{}",
               ["pageCapacity", "turnRequiredMs", "measures"])
    expect_422("measure not an object",
               json.dumps({**base, "measures": [5]}).encode(), ["measures[0]"])
    expect_422("body not an object", b"[1, 2, 3]", ["$"])
    expect_422("malformed JSON", b"{not json", ["$"])

    # All violations are reported at once, stably ordered by input position.
    expect_422(
        "all errors collected in input order",
        json.dumps({
            "pageCapacity": 0,
            "turnRequiredMs": 500,
            "measures": [
                {"height": 10, "restAfterMs": 30001},
                {"height": 10, "restAfterMs": 10},
                {"height": "x", "restAfterMs": 10},
            ],
        }).encode(),
        ["pageCapacity", "measures[0].restAfterMs", "measures[2].height"],
    )


# --------------------------------------------------------------------------
# Web service
# --------------------------------------------------------------------------

def test_web() -> None:
    if not WEB_URL:
        print("web checks skipped (WEB_URL empty)")
        return
    print("web service")
    deadline = time.time() + 60
    index_ok = proxy_ok = False
    while time.time() < deadline and not (index_ok and proxy_ok):
        try:
            resp = httpx.get(f"{WEB_URL}/", timeout=5)
            index_ok = resp.status_code == 200 and 'id="root"' in resp.text
        except httpx.HTTPError:
            pass
        try:
            proxy_ok = httpx.get(f"{WEB_URL}/api/health", timeout=5).status_code == 200
        except httpx.HTTPError:
            pass
        if not (index_ok and proxy_ok):
            time.sleep(2)
    check("web serves the frontend", index_ok)
    check("web proxies /api to the API service", proxy_ok)


def main() -> int:
    wait_for_api()
    test_known_examples()
    test_against_brute_force()
    test_large_instance()
    test_validation()
    test_web()
    print(f"\n{PASSES} checks passed, {len(FAILURES)} failed")
    if FAILURES:
        print("failed checks:")
        for name in FAILURES:
            print(f"  - {name}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
