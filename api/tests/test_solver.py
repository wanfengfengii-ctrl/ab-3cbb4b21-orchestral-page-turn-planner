"""Property tests: the DP optimizer must match exhaustive enumeration."""
from __future__ import annotations

import random

from app.solver import optimize


def brute_force(
    heights: list[int], rests: list[int], capacity: int, turn_required_ms: int
) -> tuple[int, int, int, int, list[int]]:
    """Enumerate every composition and return the best objective vector."""
    n = len(heights)
    best: tuple[int, int, int, int, list[int]] | None = None

    def rec(start: int, ends: list[int]) -> None:
        nonlocal best
        if start == n:
            pages = len(ends)
            unsafe = max_gap = sum_sq = 0
            turn_points: list[int] = []
            prev = 0
            for k, end in enumerate(ends):
                used = sum(heights[prev : end + 1])
                sum_sq += (capacity - used) ** 2
                if k < pages - 1:
                    turn_points.append(end + 1)
                    rest = rests[end]
                    if rest < turn_required_ms:
                        unsafe += 1
                        max_gap = max(max_gap, turn_required_ms - rest)
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
    assert best is not None
    return best


def vector_of(plan) -> tuple[int, int, int, int, list[int]]:
    return (
        plan.pages,
        plan.unsafe_turns,
        plan.max_gap_ms,
        plan.sum_squared_slack,
        list(plan.turn_points),
    )


def test_matches_brute_force_on_random_instances() -> None:
    rng = random.Random(20260917)
    for _ in range(500):
        n = rng.randint(1, 11)
        capacity = rng.randint(1, 20)
        heights = [rng.randint(1, capacity) for _ in range(n)]
        rests = [rng.randint(0, 1000) for _ in range(n)]
        turn_required = rng.choice([0, 1, 250, 500, 1000])
        plan = optimize(heights, rests, capacity, turn_required)
        assert vector_of(plan) == brute_force(heights, rests, capacity, turn_required)


def test_regression_max_gap_prefix_interaction() -> None:
    # A prefix with a worse max-gap but better slack sum must not be pruned:
    # a later page's gap equalises the maximum, making the slack decisive.
    plan = optimize(
        [5, 2, 8, 10, 6], [998, 594, 994, 125, 221],
        capacity=12, turn_required_ms=1000,
    )
    assert vector_of(plan) == (4, 3, 875, 81, [2, 3, 4])


def test_tie_break_prefers_lexicographically_smaller_turn_points() -> None:
    # Two 2-page splits tie on (pages, unsafe, gap, slack^2): [2] must win over [3].
    plan = optimize([3, 3, 4, 3, 3], [1000] * 5, capacity=10, turn_required_ms=500)
    assert vector_of(plan) == (2, 0, 0, 16, [2])


def test_last_page_is_excluded_from_safety_and_gap() -> None:
    plan = optimize([5, 5], [0, 0], capacity=10, turn_required_ms=30_000)
    assert vector_of(plan) == (1, 0, 0, 0, [])


def test_max_gap_is_minimised_before_slack() -> None:
    # Both 2-page splits tie on slack^2 = 16; the gap-800 split must win.
    plan = optimize([4, 4, 4], [100, 200, 0], capacity=8, turn_required_ms=1000)
    assert vector_of(plan) == (2, 1, 800, 16, [2])
