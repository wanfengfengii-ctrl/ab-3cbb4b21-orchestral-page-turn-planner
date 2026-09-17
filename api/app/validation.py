"""Request validation for the pagination API.

Every numeric value must arrive as a JSON number whose lexical form matches
``0|[1-9]\\d*`` — a non-negative integer with no leading zeros, no decimal
point and no exponent.  Decimals, exponents, strings, booleans and null are
all rejected.  We hook ``json``'s ``parse_int`` / ``parse_float`` /
``parse_constant`` so any non-conforming token is preserved as a sentinel
instead of being silently coerced to a Python number.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

MEASURES_MIN = 1
MEASURES_MAX = 500
HEIGHT_MIN = 1
HEIGHT_MAX = 30_000
CAPACITY_MIN = 1
CAPACITY_MAX = 30_000
DURATION_MIN = 0
DURATION_MAX = 30_000

_INTEGER_TOKEN = re.compile(r"0|[1-9]\d*")


class NonIntegerToken:
    """Sentinel produced by json parse hooks for non-conforming number tokens."""

    __slots__ = ("token",)

    def __init__(self, token: str) -> None:
        self.token = token

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"NonIntegerToken({self.token!r})"


def _parse_int(token: str) -> Any:
    """Accept only tokens matching ``0|[1-9]\\d*``; reject everything else."""
    if _INTEGER_TOKEN.fullmatch(token):
        return int(token)
    return NonIntegerToken(token)


@dataclass
class FieldError:
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


def parse_body(raw: bytes) -> tuple[Any, FieldError | None]:
    """Parse the raw request body, keeping non-integer tokens as sentinels."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, FieldError("$", "request body must be UTF-8 encoded JSON")
    try:
        data = json.loads(
            text,
            parse_int=_parse_int,
            parse_float=NonIntegerToken,
            parse_constant=NonIntegerToken,
        )
    except json.JSONDecodeError as exc:
        return None, FieldError(
            "$", f"invalid JSON: {exc.msg} (line {exc.lineno} column {exc.colno})"
        )
    return data, None


_TYPE_MESSAGE = (
    "must be a JSON integer matching 0|[1-9]\\d* "
    "(decimals, exponents, strings, booleans and null are rejected)"
)


def _as_int(value: Any, path: str, errors: list[FieldError]) -> int | None:
    # bool is a subclass of int, so it must be excluded explicitly.
    if isinstance(value, bool) or isinstance(value, NonIntegerToken):
        errors.append(FieldError(path, _TYPE_MESSAGE))
        return None
    if not isinstance(value, int):
        errors.append(FieldError(path, _TYPE_MESSAGE))
        return None
    return value


def _ranged(
    value: int | None, lo: int, hi: int, path: str, errors: list[FieldError]
) -> int | None:
    if value is None:
        return None
    if not lo <= value <= hi:
        errors.append(FieldError(path, f"must be between {lo} and {hi}"))
        return None
    return value


@dataclass
class ValidatedInput:
    page_capacity: int
    turn_required_ms: int
    heights: list[int]
    rests: list[int]


def validate_payload(data: Any) -> tuple[ValidatedInput | None, list[FieldError]]:
    """Validate the decoded payload, collecting *all* errors.

    Errors are appended in a stable input-position order: ``pageCapacity``,
    ``turnRequiredMs``, ``measures`` itself, then per measure (index order)
    ``height`` followed by ``restAfterMs``.
    """
    if not isinstance(data, dict):
        return None, [FieldError("$", "request body must be a JSON object")]

    errors: list[FieldError] = []

    if "pageCapacity" not in data:
        errors.append(FieldError("pageCapacity", "is required"))
        capacity: int | None = None
    else:
        capacity = _ranged(
            _as_int(data["pageCapacity"], "pageCapacity", errors),
            CAPACITY_MIN,
            CAPACITY_MAX,
            "pageCapacity",
            errors,
        )

    if "turnRequiredMs" not in data:
        errors.append(FieldError("turnRequiredMs", "is required"))
        turn_required: int | None = None
    else:
        turn_required = _ranged(
            _as_int(data["turnRequiredMs"], "turnRequiredMs", errors),
            DURATION_MIN,
            DURATION_MAX,
            "turnRequiredMs",
            errors,
        )

    heights: list[int] = []
    rests: list[int] = []
    if "measures" not in data:
        errors.append(FieldError("measures", "is required"))
    elif not isinstance(data["measures"], list):
        errors.append(FieldError("measures", "must be an array of objects"))
    else:
        raw_measures: list[Any] = data["measures"]
        if not MEASURES_MIN <= len(raw_measures) <= MEASURES_MAX:
            errors.append(
                FieldError(
                    "measures",
                    f"must contain between {MEASURES_MIN} and {MEASURES_MAX} "
                    f"entries (got {len(raw_measures)})",
                )
            )
        for i, measure in enumerate(raw_measures):
            base = f"measures[{i}]"
            if not isinstance(measure, dict):
                errors.append(
                    FieldError(base, "must be an object with height and restAfterMs")
                )
                continue

            if "height" not in measure:
                errors.append(FieldError(f"{base}.height", "is required"))
                height = None
            else:
                height = _ranged(
                    _as_int(measure["height"], f"{base}.height", errors),
                    HEIGHT_MIN,
                    HEIGHT_MAX,
                    f"{base}.height",
                    errors,
                )
                if height is not None and capacity is not None and height > capacity:
                    errors.append(
                        FieldError(
                            f"{base}.height",
                            f"must not exceed pageCapacity ({capacity})",
                        )
                    )

            if "restAfterMs" not in measure:
                errors.append(FieldError(f"{base}.restAfterMs", "is required"))
                rest = None
            else:
                rest = _ranged(
                    _as_int(measure["restAfterMs"], f"{base}.restAfterMs", errors),
                    DURATION_MIN,
                    DURATION_MAX,
                    f"{base}.restAfterMs",
                    errors,
                )

            if height is not None and rest is not None:
                heights.append(height)
                rests.append(rest)

    if errors:
        return None, errors
    # capacity/turn_required are guaranteed non-None when errors is empty.
    return ValidatedInput(capacity, turn_required, heights, rests), []  # type: ignore[arg-type]
