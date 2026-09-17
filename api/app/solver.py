"""Dynamic-programming pagination optimizer.

Partitions a sequence of measures into contiguous pages whose summed heights
never exceed the page capacity.  Candidate plans are ordered lexicographically
by the objective vector

    (pages, unsafeTurns, maxGapMs, sumSquaredSlack, turnPoints)

where

* ``pages``            – number of pages (minimised first);
* ``unsafeTurns``      – non-last pages whose closing measure's ``restAfterMs``
                         is below ``turnRequiredMs``;
* ``maxGapMs``         – maximum ``turnRequiredMs - restAfterMs`` over unsafe
                         non-last pages, or 0 when there are none;
* ``sumSquaredSlack``  – sum over *all* pages of ``(capacity - usedHeight)**2``;
* ``turnPoints``       – 1-based indices of the closing measures of all
                         non-last pages, compared lexicographically.

A single lexicographic DP over the whole vector is *not* valid: ``maxGapMs``
combines with ``max`` rather than addition, so a prefix that is worse on
``maxGapMs`` but better on ``sumSquaredSlack`` can still lead to the optimum
once a later page's gap dominates the maximum.  We therefore optimise in two
phases:

* Phase A minimises ``(pages, unsafeTurns, maxGapMs)``.  This is a valid
  lexicographic DP because no component below the ``max``-combined one exists
  to break ties after two prefixes' gaps are equalised.
* Phase B replays the DP with every non-last page's gap capped at the phase-A
  optimum, minimising ``(pages, unsafeTurns, sumSquaredSlack, turnPointCode)``
  — all additive components, so the lexicographic DP is exact.  The turn-point
  sequence is encoded as a base-(n+1) integer whose most significant digit is
  the first turn point, which makes integer comparison identical to
  lexicographic comparison of equal-length sequences.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    pages: int
    unsafe_turns: int
    max_gap_ms: int
    sum_squared_slack: int
    turn_points: tuple[int, ...]  # 1-based closing measures of non-last pages
    page_end_indices: tuple[int, ...]  # 1-based closing measure of every page


def optimize(
    heights: list[int],
    rests: list[int],
    capacity: int,
    turn_required_ms: int,
) -> Plan:
    n = len(heights)
    prefix = [0] * (n + 1)
    for i, height in enumerate(heights, 1):
        prefix[i] = prefix[i - 1] + height

    def page_turn(end: int) -> tuple[int, int]:
        """(unsafe, gap) contributed by a page closing at measure ``end``."""
        if end == n:  # the last page never turns
            return 0, 0
        rest = rests[end - 1]
        if rest >= turn_required_ms:
            return 0, 0
        return 1, turn_required_ms - rest

    # ---- Phase A: minimise (pages, unsafeTurns, maxGapMs) --------------------
    dp_a: list[tuple[int, int, int] | None] = [None] * (n + 1)
    dp_a[0] = (0, 0, 0)
    for end in range(1, n + 1):
        unsafe, gap = page_turn(end)
        best: tuple[int, int, int] | None = None
        for start in range(end - 1, -1, -1):
            used = prefix[end] - prefix[start]
            if used > capacity:
                break  # heights are positive, earlier starts only get worse
            base = dp_a[start]
            if base is None:  # pragma: no cover - unreachable for valid input
                continue
            candidate = (base[0] + 1, base[1] + unsafe, max(base[2], gap))
            if best is None or candidate < best:
                best = candidate
        dp_a[end] = best

    final_a = dp_a[n]
    assert final_a is not None  # guaranteed: every height <= capacity
    pages, unsafe_turns, max_gap = final_a

    # ---- Phase B: minimise (pages, unsafeTurns, sumSquaredSlack, code) -------
    # Every non-last page with gap > max_gap is forbidden; the remaining
    # components are additive, so a plain lexicographic DP is exact.
    radix = n + 1
    # Weight of the k-th (1-based) turn point: there are pages-1 turn points.
    # Indices beyond pages-1 stay 0; candidates using them have more pages
    # than the phase-A optimum and can never win the comparison.
    weight = [0] * (n + 2)
    if pages > 1:
        weight[pages - 1] = 1
        for k in range(pages - 2, 0, -1):
            weight[k] = weight[k + 1] * radix

    dp_b: list[tuple[int, int, int, int] | None] = [None] * (n + 1)
    dp_b[0] = (0, 0, 0, 0)
    for end in range(1, n + 1):
        unsafe, gap = page_turn(end)
        is_last = end == n
        if gap > max_gap:
            # No page closing here may contribute a gap above the optimum.
            # (Only possible for non-last pages; the last page has gap 0.)
            dp_b[end] = None
            continue
        best_b: tuple[int, int, int, int] | None = None
        for start in range(end - 1, -1, -1):
            used = prefix[end] - prefix[start]
            if used > capacity:
                break
            base = dp_b[start]
            if base is None:
                continue
            slack = capacity - used
            code = base[3] if is_last else base[3] + end * weight[base[0] + 1]
            candidate = (
                base[0] + 1,
                base[1] + unsafe,
                base[2] + slack * slack,
                code,
            )
            if best_b is None or candidate < best_b:
                best_b = candidate
        dp_b[end] = best_b

    final_b = dp_b[n]
    assert final_b is not None  # the phase-A optimum is always feasible here
    _, _, sum_squared_slack, code = final_b

    turn_points = tuple(
        code // weight[k] % radix for k in range(1, pages)
    )
    return Plan(
        pages=pages,
        unsafe_turns=unsafe_turns,
        max_gap_ms=max_gap,
        sum_squared_slack=sum_squared_slack,
        turn_points=turn_points,
        page_end_indices=turn_points + (n,),
    )


def build_response(
    heights: list[int],
    rests: list[int],
    capacity: int,
    turn_required_ms: int,
) -> dict:
    """Run the optimizer and assemble the full API response payload."""
    n = len(heights)
    plan = optimize(heights, rests, capacity, turn_required_ms)

    prefix = [0] * (n + 1)
    for i, height in enumerate(heights, 1):
        prefix[i] = prefix[i - 1] + height

    pages = []
    start = 1  # 1-based, inclusive
    for page_no, end in enumerate(plan.page_end_indices, 1):
        used = prefix[end] - prefix[start - 1]
        is_last = end == n
        turn = None
        if not is_last:
            rest = rests[end - 1]
            safe = rest >= turn_required_ms
            turn = {
                "restAfterMs": rest,
                "requiredMs": turn_required_ms,
                "safe": safe,
                "gapMs": 0 if safe else turn_required_ms - rest,
            }
        pages.append(
            {
                "page": page_no,
                "startMeasure": start,
                "endMeasure": end,
                "measureCount": end - start + 1,
                "usedHeight": used,
                "remainingCapacity": capacity - used,
                "isLastPage": is_last,
                "turn": turn,
            }
        )
        start = end + 1

    return {
        "objective": {
            "pages": plan.pages,
            "unsafeTurns": plan.unsafe_turns,
            "maxGapMs": plan.max_gap_ms,
            "sumSquaredSlack": plan.sum_squared_slack,
        },
        "turnPoints": list(plan.turn_points),
        "pageEndIndices": list(plan.page_end_indices),
        "pages": pages,
    }
