"""Ratios with explicit denominators, nearest-rank percentiles and interval unions."""
from __future__ import annotations

import math
from typing import Any, Iterable

# Reporting caveat thresholds only (not pass/fail criteria). nearest-rank p95 equals the maximum for n < 20.
MIN_SAMPLES_P50 = 10
MIN_SAMPLES_P95 = 20


def ratio(numerator: int | float, denominator: int | float) -> dict[str, Any]:
    """A rate that always carries its counts. An empty denominator is null, never 0 and never 1."""
    value = None if denominator == 0 else round(numerator / denominator, 6)
    return {"num": numerator, "den": denominator, "value": value}


def f1(precision: dict[str, Any], recall: dict[str, Any]) -> float | None:
    p, r = precision["value"], recall["value"]
    if p is None or r is None:
        return None
    return 0.0 if p + r == 0 else round(2 * p * r / (p + r), 6)


def nearest_rank(sorted_values: list[float], quantile: float) -> float:
    return sorted_values[max(1, math.ceil(quantile * len(sorted_values))) - 1]


def distribution(samples: Iterable[float]) -> dict[str, Any]:
    values = sorted(samples)
    n = len(values)
    caveats: list[str] = []
    if n == 0:
        return {"n": 0, "min": None, "p50": None, "p95": None, "max": None, "caveats": ["no_samples"]}
    if n < MIN_SAMPLES_P50:
        caveats.append(f"p50_insufficient_samples(n<{MIN_SAMPLES_P50})")
    if n < MIN_SAMPLES_P95:
        caveats.append(f"p95_insufficient_samples(n<{MIN_SAMPLES_P95}; nearest-rank p95 equals max)")
    return {"n": n, "min": round(values[0], 3), "p50": round(nearest_rank(values, 0.50), 3),
            "p95": round(nearest_rank(values, 0.95), 3), "max": round(values[-1], 3), "caveats": caveats}


def union_length(intervals: list[tuple[float, float]]) -> float:
    """Length covered by the union of intervals; overlapping (parallel) spans are counted once."""
    total = 0.0
    cursor = None
    for start, end in sorted(intervals):
        if cursor is None or start > cursor:
            total += end - start
            cursor = end
        elif end > cursor:
            total += end - cursor
            cursor = end
    return total


def overlaps(intervals: list[tuple[float, float]]) -> bool:
    reach = None
    for start, end in sorted(intervals):
        if reach is not None and start < reach:
            return True
        reach = end if reach is None else max(reach, end)
    return False
