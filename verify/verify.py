"""One-shot end-to-end verification for the page-turn planner stack.

Runs against the api and web services over the compose network:

* waits for the API to become healthy,
* checks the DP optimum against an independent brute-force enumeration
  (deterministic edge cases + seeded random instances),
* checks the per-page details are consistent with the breaks,
* exercises the validation rules (lexical, range, cross-field, batch 422
  with errors in stable input order),
* checks the web service serves the frontend.

Exits 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API_URL", "http://api:8000").rstrip("/")
WEB = os.environ.get("WEB_URL", "http://web").rstrip("/")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'ok' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def post_plan(payload: object) -> tuple[int, dict]:
    return post_raw(json.dumps(payload).encode("utf-8"))


def post_raw(raw: bytes) -> tuple[int, dict]:
    request = urllib.request.Request(
        API + "/api/plan",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def wait_for_api() -> bool:
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(API + "/api/health", timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


# --------------------------------------------------------------------------
# Independent brute-force optimum: enumerate every composition of the measure
# sequence into feasible pages and take the lexicographic minimum of
# (pages, unsafe, max_gap, slack_squares, breaks).
# --------------------------------------------------------------------------

def brute_force(heights: list[int], rests: list[int], cap: int, turn: int):
    n = len(heights)
    best = None

    def rec(start: int, ends: list[int]) -> None:
        nonlocal best
        if start == n:
            pages = len(ends)
            unsafe = sum(1 for e in ends[:-1] if rests[e - 1] < turn)
            gap = max([turn - rests[e - 1] for e in ends[:-1] if rests[e - 1] < turn] or [0])
            slack2 = 0
            prev = 0
            for e in ends:
                slack2 += (cap - sum(heights[prev:e])) ** 2
                prev = e
            breaks = tuple(ends[:-1])
            cand = (pages, unsafe, gap, slack2, breaks)
            if best is None or cand < best:
                best = cand
            return
        total = 0
        for e in range(start + 1, n + 1):
            total += heights[e - 1]
            if total > cap:
                break
            rec(e, ends + [e])

    rec(0, [])
    return best


def check_plan(name: str, heights: list[int], rests: list[int], cap: int, turn: int) -> None:
    payload = {
        "pageCapacity": cap,
        "turnRequiredMs": turn,
        "measures": [{"height": h, "restAfterMs": r} for h, r in zip(heights, rests)],
    }
    status, body = post_plan(payload)
    if status != 200:
        check(name, False, f"status {status}: {body}")
        return
    want = brute_force(heights, rests, cap, turn)
    got = (
        body["objective"]["pages"],
        body["objective"]["unsafeTurns"],
        body["objective"]["maxGapMs"],
        body["objective"]["slackSquares"],
        tuple(body["breaks"]),
    )
    check(name, got == want, f"got {got}, want {want}")
    if got != want:
        return

    # Per-page details must agree with the breaks and the input.
    ok = len(body["pages"]) == want[0]
    start = 1
    for index, page in enumerate(body["pages"], start=1):
        end = (list(body["breaks"]) + [len(heights)])[index - 1]
        height_sum = sum(heights[start - 1 : end])
        ok = ok and page["index"] == index
        ok = ok and page["start"] == start and page["end"] == end
        ok = ok and page["heightSum"] == height_sum
        ok = ok and page["remaining"] == cap - height_sum
        if end == len(heights):
            ok = ok and page["turn"] is None
        else:
            rest = rests[end - 1]
            safe = rest >= turn
            turn_info = page["turn"] or {}
            ok = ok and turn_info.get("safe") == safe
            ok = ok and turn_info.get("restAfterMs") == rest
            ok = ok and turn_info.get("gapMs") == (0 if safe else turn - rest)
        start = end + 1
    check(name + " · 逐页明细一致", ok, json.dumps(body, ensure_ascii=False))


def check_422(name: str, payload: object = None, raw: bytes = None,
              want_paths: list[str] | None = None) -> None:
    if raw is not None:
        status, body = post_raw(raw)
    else:
        status, body = post_plan(payload)
    ok = status == 422 and isinstance(body.get("errors"), list) and len(body["errors"]) > 0
    if ok and want_paths is not None:
        got_paths = [e.get("path") for e in body["errors"]]
        ok = got_paths == want_paths
        if not ok:
            detail = f"paths {got_paths}, want {want_paths}"
            check(name, False, detail)
            return
    check(name, ok, f"status {status}: {json.dumps(body, ensure_ascii=False)[:400]}")


def main() -> int:
    if not wait_for_api():
        check("api 健康检查", False, f"{API}/api/health 90 秒内未就绪")
        return finish()
    check("api 健康检查", True)

    # ---- deterministic planner cases -------------------------------------
    check_plan("单小节单页", [10], [0], 10, 500)
    check_plan("全部安全翻页", [30, 40, 20], [600, 800, 0], 100, 500)
    check_plan("不安全翻页与缺口", [10, 10, 10], [100, 600, 0], 10, 500)
    # 5 measures of height 2, capacity 4, all rests safe: the first three
    # objectives tie for [1][23][45], [12][3][45], [12][34][5] (slack^2 = 4);
    # the breaks tie-break must pick (1, 3).
    check_plan("并列时取字典序最小分页点", [2, 2, 2, 2, 2], [5, 5, 5, 5, 5], 4, 5)
    check_plan("休止不足时优先页数", [5, 5], [0, 0], 10, 100)
    check_plan("容量刚好逐页", [7, 7, 7, 7], [0, 0, 0, 0], 7, 30000)
    check_plan("零休止阈值零", [3, 3, 3], [0, 0, 0], 9, 0)
    # Regression: a prefix with a smaller gap but worse slack must not prune
    # the prefix that wins once a later page forces the larger gap anyway
    # (the maximum-gap objective has no plain prefix optimal substructure).
    check_plan(
        "最大缺口无前缀最优子结构（回归）",
        [6, 10, 4, 4, 3, 8, 3, 8, 10, 6, 7],
        [718, 562, 482, 775, 550, 821, 680, 845, 223, 780, 253],
        10,
        900,
    )

    # ---- seeded randomized planner cases ----------------------------------
    rng = random.Random(20260917)
    for trial in range(40):
        n = rng.randint(1, 10)
        cap = rng.randint(3, 30)
        heights = [rng.randint(1, cap) for _ in range(n)]
        rests = [rng.choice([0, 0, 120, 300, 500, 900]) for _ in range(n)]
        turn = rng.choice([0, 100, 300, 500])
        check_plan(f"随机用例 #{trial + 1}", heights, rests, cap, turn)

    # ---- validation: every bad input is rejected wholesale with 422 -------
    base = {"pageCapacity": 10, "turnRequiredMs": 5,
            "measures": [{"height": 5, "restAfterMs": 5}]}

    def mutated(**changes):
        doc = json.loads(json.dumps(base))
        doc.update(changes)
        return doc

    check_422("拒绝小数 height", mutated(measures=[{"height": 1.5, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝指数 height", mutated(measures=[{"height": 1e2, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝字符串 height", mutated(measures=[{"height": "5", "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝布尔 height", mutated(measures=[{"height": True, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝空值 height", mutated(measures=[{"height": None, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝负数 height", mutated(measures=[{"height": -5, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝前导零（非法 JSON）", raw=b'{"pageCapacity": 01, "turnRequiredMs": 5, "measures": [{"height": 5, "restAfterMs": 5}]}',
              want_paths=["$"])
    check_422("拒绝 height 0", mutated(measures=[{"height": 0, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝 height 30001", mutated(measures=[{"height": 30001, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝 pageCapacity 0", mutated(pageCapacity=0),
              want_paths=["pageCapacity"])
    check_422("拒绝 pageCapacity 30001", mutated(pageCapacity=30001),
              want_paths=["pageCapacity"])
    check_422("拒绝 turnRequiredMs -1", mutated(turnRequiredMs=-1),
              want_paths=["turnRequiredMs"])
    check_422("拒绝 restAfterMs 30001", mutated(measures=[{"height": 5, "restAfterMs": 30001}]),
              want_paths=["measures[0].restAfterMs"])
    check_422("拒绝 height 超过容量", mutated(measures=[{"height": 11, "restAfterMs": 0}]),
              want_paths=["measures[0].height"])
    check_422("拒绝空 measures", mutated(measures=[]),
              want_paths=["measures"])
    check_422("拒绝 501 个小节", mutated(measures=[{"height": 1, "restAfterMs": 0}] * 501),
              want_paths=["measures"])
    check_422("拒绝缺少 restAfterMs", mutated(measures=[{"height": 5}]),
              want_paths=["measures[0].restAfterMs"])
    check_422("拒绝小节多余键", mutated(measures=[{"height": 5, "restAfterMs": 0, "tempo": 120}]),
              want_paths=["measures[0].tempo"])
    check_422("拒绝顶层多余键", mutated(foo=1), want_paths=["foo"])
    check_422("拒绝缺少 pageCapacity", {"turnRequiredMs": 5, "measures": [{"height": 5, "restAfterMs": 5}]},
              want_paths=["pageCapacity"])
    check_422("拒绝非对象请求体", [1, 2, 3], want_paths=["$"])
    check_422("拒绝非法 JSON", raw=b'{"pageCapacity":', want_paths=["$"])
    check_422("拒绝重复键", raw=b'{"pageCapacity": 10, "pageCapacity": 10, "turnRequiredMs": 5, "measures": [{"height": 5, "restAfterMs": 5}]}',
              want_paths=["pageCapacity"])

    # Multiple errors in one batch, reported in stable input order.
    check_422(
        "批量错误按输入位置稳定排列",
        {
            "pageCapacity": 0,
            "turnRequiredMs": 5,
            "measures": [
                {"height": 1, "restAfterMs": "x"},
                {"height": 2, "restAfterMs": 3},
                {"height": 0, "restAfterMs": 3},
            ],
        },
        want_paths=["pageCapacity", "measures[0].restAfterMs", "measures[2].height"],
    )

    # ---- boundary values are accepted -------------------------------------
    status, body = post_plan(
        {"pageCapacity": 30000, "turnRequiredMs": 30000,
         "measures": [{"height": 30000, "restAfterMs": 30000}]}
    )
    check("边界值 30000 全部接受", status == 200 and body["objective"]["pages"] == 1,
          f"status {status}: {json.dumps(body)[:200]}")

    status, body = post_plan(
        {"pageCapacity": 1, "turnRequiredMs": 0,
         "measures": [{"height": 1, "restAfterMs": 0}] * 500}
    )
    check("500 个小节上限接受", status == 200 and body["objective"]["pages"] == 500,
          f"status {status}")

    # ---- web service -------------------------------------------------------
    web_ok = False
    for _ in range(30):
        try:
            with urllib.request.urlopen(WEB + "/", timeout=3) as response:
                html = response.read().decode("utf-8", "replace")
                if response.status == 200 and 'id="root"' in html:
                    web_ok = True
                    break
        except Exception:
            pass
        time.sleep(1)
    check("web 服务返回前端页面", web_ok)

    return finish()


def finish() -> int:
    total = "全部检查通过" if not failures else f"{len(failures)} 项失败: {failures}"
    print(f"\n=== {total} ===")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
