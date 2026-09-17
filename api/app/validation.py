"""Strict request validation for the planner API.

Every numeric value must be a JSON number whose literal matches
``0|[1-9]\\d*`` — decimals, exponents, strings, booleans, nulls, negative
numbers and leading zeros are all rejected.  To inspect the exact literals,
the body is decoded with hooks that keep the raw tokens and preserve object
pair order, so validation errors can be reported stably in input order.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .planner import Measure

MAX_VALUE = 30000
MAX_MEASURES = 500
INT_LITERAL = re.compile(r"0|[1-9]\d*")


class JObject:
    """A JSON object that preserves pair order (and duplicate keys)."""

    __slots__ = ("pairs",)

    def __init__(self, pairs: List[Tuple[str, object]]):
        self.pairs = pairs


class JNumber:
    """A JSON number that keeps its raw literal."""

    __slots__ = ("raw", "is_float")

    def __init__(self, raw: str, is_float: bool = False):
        self.raw = raw
        self.is_float = is_float


@dataclass(frozen=True)
class Issue:
    path: str
    message: str


@dataclass(frozen=True)
class ParsedRequest:
    page_capacity: int
    turn_required_ms: int
    measures: List[Measure]


def decode_body(raw: bytes) -> Tuple[Optional[object], Optional[Issue]]:
    """Decode the request body, keeping number literals and pair order."""
    try:
        doc = json.loads(
            raw,
            parse_int=lambda s: JNumber(s),
            parse_float=lambda s: JNumber(s, is_float=True),
            parse_constant=lambda s: JNumber(s, is_float=True),  # NaN/Infinity
            object_pairs_hook=JObject,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, Issue("$", f"body is not valid JSON: {exc}")
    return doc, None


def validate(doc: object) -> Tuple[Optional[ParsedRequest], List[Issue]]:
    """Validate the decoded document; errors are collected in input order."""
    issues: List[Issue] = []
    if not isinstance(doc, JObject):
        return None, [Issue("$", "body must be a JSON object")]

    page_capacity: Optional[int] = None
    turn_required_ms: Optional[int] = None
    measures: Optional[List[Measure]] = None
    seen = set()
    for key, value in doc.pairs:
        if key in seen:
            issues.append(Issue(key, "duplicate key"))
            continue
        seen.add(key)
        if key == "pageCapacity":
            page_capacity = _read_int(value, key, 1, MAX_VALUE, issues)
        elif key == "turnRequiredMs":
            turn_required_ms = _read_int(value, key, 0, MAX_VALUE, issues)
        elif key == "measures":
            measures = _read_measures(value, key, issues)
        else:
            issues.append(
                Issue(key, "unknown key; allowed: pageCapacity, turnRequiredMs, measures")
            )
    for required in ("pageCapacity", "turnRequiredMs", "measures"):
        if required not in seen:
            issues.append(Issue(required, "missing required key"))

    if issues:
        return None, issues

    assert page_capacity is not None and turn_required_ms is not None
    assert measures is not None
    # Cross-field rule, reported in measure (input) order.
    for index, measure in enumerate(measures):
        if measure.height > page_capacity:
            issues.append(
                Issue(f"measures[{index}].height", "must not exceed pageCapacity")
            )
    if issues:
        return None, issues

    return ParsedRequest(page_capacity, turn_required_ms, measures), []


def _read_int(
    value: object, path: str, minimum: int, maximum: int, issues: List[Issue]
) -> Optional[int]:
    if isinstance(value, JNumber):
        if value.is_float:
            issues.append(
                Issue(
                    path,
                    "must be an integer literal matching 0|[1-9]\\d* "
                    "(decimals, exponents and NaN/Infinity are rejected)",
                )
            )
            return None
        if not INT_LITERAL.fullmatch(value.raw):
            issues.append(
                Issue(path, "must match 0|[1-9]\\d* (no sign, no leading zeros)")
            )
            return None
        number = int(value.raw)
        if number < minimum or number > maximum:
            issues.append(Issue(path, f"must be between {minimum} and {maximum}"))
            return None
        return number
    if isinstance(value, bool) or value is None:
        issues.append(Issue(path, "must be a JSON number, not a boolean or null"))
    elif isinstance(value, str):
        issues.append(Issue(path, "must be a JSON number, not a string"))
    elif isinstance(value, list):
        issues.append(Issue(path, "must be a JSON number, not an array"))
    else:
        issues.append(Issue(path, "must be a JSON number, not an object"))
    return None


def _read_measures(
    value: object, path: str, issues: List[Issue]
) -> Optional[List[Measure]]:
    if not isinstance(value, list):
        issues.append(Issue(path, "must be an array of measures"))
        return None
    if len(value) == 0:
        issues.append(Issue(path, "must contain at least 1 measure"))
    elif len(value) > MAX_MEASURES:
        issues.append(Issue(path, f"must contain at most {MAX_MEASURES} measures"))
    measures: List[Optional[Measure]] = []
    for index, item in enumerate(value):
        measures.append(_read_measure(item, f"{path}[{index}]", issues))
    if any(m is None for m in measures):
        return None
    return measures  # type: ignore[return-value]


def _read_measure(
    value: object, path: str, issues: List[Issue]
) -> Optional[Measure]:
    if not isinstance(value, JObject):
        issues.append(Issue(path, "must be an object with height and restAfterMs"))
        return None
    height: Optional[int] = None
    rest_after_ms: Optional[int] = None
    seen = set()
    for key, item in value.pairs:
        item_path = f"{path}.{key}"
        if key in seen:
            issues.append(Issue(item_path, "duplicate key"))
            continue
        seen.add(key)
        if key == "height":
            height = _read_int(item, item_path, 1, MAX_VALUE, issues)
        elif key == "restAfterMs":
            rest_after_ms = _read_int(item, item_path, 0, MAX_VALUE, issues)
        else:
            issues.append(
                Issue(item_path, "unknown key; only height and restAfterMs are allowed")
            )
    for required in ("height", "restAfterMs"):
        if required not in seen:
            issues.append(Issue(f"{path}.{required}", "missing required key"))
    if height is None or rest_after_ms is None:
        return None
    return Measure(height=height, rest_after_ms=rest_after_ms)
