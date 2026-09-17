"""Dynamic-programming page planner for orchestral scores.

A plan splits the measure sequence into contiguous pages whose height sums
never exceed the page capacity.  Every page except the last one is followed by
a page turn; a turn is *safe* when the rest after the page's last measure is
at least ``turn_required_ms``.  Plans are ordered lexicographically by

1. page count (fewer is better),
2. number of unsafe turns,
3. maximum rest gap ``turn_required_ms - rest_after_ms`` over unsafe non-last
   pages (0 when there are none),
4. sum of squared remaining capacities over all pages,

and ties are broken by the lexicographically smallest sequence of 1-based end
indices of the non-last pages.  The optimum is therefore unique and
reproducible.

The maximum-gap objective combines with ``max`` rather than ``+``, so a plain
prefix DP has no optimal substructure (a prefix with a worse gap but better
slack can win once a later page forces an even larger gap).  The solver
therefore works in three phases:

* Phase 1 — lexicographic minimum of (pages, unsafe turns); both objectives
  are additive, so a simple prefix DP is exact.
* Phase 2 — the minimum achievable maximum gap G*.  "Is there a (P*, U*) plan
  whose gaps are all <= G?" is a per-page-end constraint (the rest after a
  non-last page's final measure must be >= turn_required_ms - G), so G* is
  found by binary search over the candidate gap values with an O(n^2)
  feasibility DP.
* Phase 3 — with the gap bound turned into allowed page ends, all remaining
  objectives are additive and are folded into one integer weight
  ``pages*M2 + unsafe*M1 + slack_squares`` (weights dominate the attainable
  ranges, so minimizing the weight is exactly the lexicographic minimum).
  The DP minimizes ``(weight, breaks)`` so the breaks tie-break falls out of
  ordinary tuple comparison.

Each phase is O(n^2); n <= 500.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class Measure:
    height: int
    rest_after_ms: int


@dataclass(frozen=True)
class TurnInfo:
    safe: bool
    rest_after_ms: int
    gap_ms: int


@dataclass(frozen=True)
class PageDetail:
    index: int  # 1-based page number
    start: int  # 1-based first measure of the page
    end: int  # 1-based last measure of the page
    height_sum: int
    remaining: int
    turn: Optional[TurnInfo]  # None on the last page: no turn needed


@dataclass(frozen=True)
class Objective:
    pages: int
    unsafe_turns: int
    max_gap_ms: int
    slack_squares: int


@dataclass(frozen=True)
class Plan:
    objective: Objective
    breaks: Tuple[int, ...]  # 1-based end measures of the non-last pages
    pages: Tuple[PageDetail, ...]


def solve(measures: List[Measure], page_capacity: int, turn_required_ms: int) -> Plan:
    n = len(measures)
    heights = [m.height for m in measures]
    rests = [m.rest_after_ms for m in measures]

    # Phase 1: lexicographic minimum of (pages, unsafe turns).
    unconstrained = _min_pages_unsafe(
        heights, rests, page_capacity, turn_required_ms, min_rest=0
    )
    assert unconstrained is not None  # min_rest=0 never blocks a page end
    pages_star, unsafe_star = unconstrained

    # Phase 2: minimum achievable maximum gap G* among (P*, U*) plans.
    if unsafe_star == 0:
        gap_star = 0  # no unsafe non-last pages: the gap is 0 by definition
    else:
        # The maximum gap of any plan is one of these candidate values.
        candidates = sorted(
            {turn_required_ms - r for r in rests if r < turn_required_ms}
        )
        lo, hi = 0, len(candidates) - 1  # feasibility at hi always holds
        while lo < hi:
            mid = (lo + hi) // 2
            if _min_pages_unsafe(
                heights,
                rests,
                page_capacity,
                turn_required_ms,
                min_rest=turn_required_ms - candidates[mid],
            ) == (pages_star, unsafe_star):
                hi = mid
            else:
                lo = mid + 1
        gap_star = candidates[lo]

    # Phase 3: minimize (pages, unsafe, slack^2, breaks) under the gap bound.
    weight, breaks = _solve_weighted(
        heights,
        rests,
        page_capacity,
        turn_required_ms,
        min_rest=turn_required_ms - gap_star,
    )

    slack_max = n * page_capacity * page_capacity
    m1 = slack_max + 1
    m2 = (n + 1) * m1
    pages, rem = divmod(weight, m2)
    unsafe, slack_squares = divmod(rem, m1)
    assert (pages, unsafe) == (pages_star, unsafe_star)

    pages_out: List[PageDetail] = []
    start = 1
    for index, end in enumerate((*breaks, n), start=1):
        height_sum = sum(heights[start - 1 : end])
        remaining = page_capacity - height_sum
        if end == n:
            turn = None
        else:
            rest = rests[end - 1]
            safe = rest >= turn_required_ms
            turn = TurnInfo(
                safe=safe,
                rest_after_ms=rest,
                gap_ms=0 if safe else turn_required_ms - rest,
            )
        pages_out.append(
            PageDetail(
                index=index,
                start=start,
                end=end,
                height_sum=height_sum,
                remaining=remaining,
                turn=turn,
            )
        )
        start = end + 1

    return Plan(
        objective=Objective(
            pages=pages,
            unsafe_turns=unsafe,
            max_gap_ms=gap_star,
            slack_squares=slack_squares,
        ),
        breaks=breaks,
        pages=tuple(pages_out),
    )


def _min_pages_unsafe(
    heights: List[int],
    rests: List[int],
    capacity: int,
    turn_required_ms: int,
    min_rest: int,
) -> Optional[Tuple[int, int]]:
    """Lexicographic min of (pages, unsafe turns), or None if infeasible.

    Only non-last pages whose last measure's rest is >= ``min_rest`` may be
    used (a non-last page always turns at its end).  Both objectives are
    additive, so a prefix DP with tuple comparison is exact.
    """
    n = len(heights)
    g: List[Optional[Tuple[int, int]]] = [None] * (n + 1)
    g[0] = (0, 0)
    for j in range(1, n + 1):
        if rests[j - 1] < min_rest:
            continue  # no turning page may end at j
        best: Optional[Tuple[int, int]] = None
        total = 0
        for i in range(j, 0, -1):  # candidate page covers measures[i-1:j]
            total += heights[i - 1]
            if total > capacity:
                break
            prev = g[i - 1]
            if prev is None:
                continue
            unsafe = 1 if rests[j - 1] < turn_required_ms else 0
            cand = (prev[0] + 1, prev[1] + unsafe)
            if best is None or cand < best:
                best = cand
        g[j] = best

    # The last page never turns: it adds one page and no unsafe turn.
    best_full: Optional[Tuple[int, int]] = None
    total = 0
    for k in range(n, 0, -1):
        total += heights[k - 1]
        if total > capacity:
            break
        prev = g[k - 1]
        if prev is None:
            continue
        cand = (prev[0] + 1, prev[1])
        if best_full is None or cand < best_full:
            best_full = cand
    return best_full  # None: the rest constraint makes every plan infeasible


def _solve_weighted(
    heights: List[int],
    rests: List[int],
    capacity: int,
    turn_required_ms: int,
    min_rest: int,
) -> Tuple[int, Tuple[int, ...]]:
    """Minimize (weight, breaks) under the page-end rest constraint.

    ``weight = pages*M2 + unsafe*M1 + slack_squares`` where M1 exceeds any
    attainable slack-squares sum and M2 exceeds any attainable
    ``unsafe*M1 + slack_squares``, so the single integer weight orders plans
    exactly like the lexicographic triple (pages, unsafe, slack_squares).
    """
    n = len(heights)
    slack_max = n * capacity * capacity
    m1 = slack_max + 1
    m2 = (n + 1) * m1

    g: List[Optional[Tuple[int, Tuple[int, ...]]]] = [None] * (n + 1)
    g[0] = (0, ())
    for j in range(1, n + 1):
        if rests[j - 1] < min_rest:
            continue  # no turning page may end at j
        best: Optional[Tuple[int, Tuple[int, ...]]] = None
        total = 0
        for i in range(j, 0, -1):  # candidate page covers measures[i-1:j]
            total += heights[i - 1]
            if total > capacity:
                break
            prev = g[i - 1]
            if prev is None:
                continue
            slack = capacity - total
            unsafe = 1 if rests[j - 1] < turn_required_ms else 0
            cand = (
                prev[0] + m2 + unsafe * m1 + slack * slack,
                prev[1] + (j,),
            )
            if best is None or cand < best:
                best = cand
        g[j] = best

    # The last page never turns: one more page plus its squared slack.
    best_full: Optional[Tuple[int, Tuple[int, ...]]] = None
    total = 0
    for k in range(n, 0, -1):
        total += heights[k - 1]
        if total > capacity:
            break
        prev = g[k - 1]
        if prev is None:
            continue
        slack = capacity - total
        cand = (prev[0] + m2 + slack * slack, prev[1])
        if best_full is None or cand < best_full:
            best_full = cand
    assert best_full is not None  # every height <= capacity, so a plan exists
    return best_full
