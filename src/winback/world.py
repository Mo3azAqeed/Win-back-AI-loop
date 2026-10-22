"""The made-up merchants: who exists and when they arrive."""

import math
from dataclasses import dataclass

from winback.draws import draw
from winback.segments import Segment
from winback.settings import Settings

DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class Merchant:
    key: str
    arrival_day: float
    existing: bool
    start_segment: Segment


def _whole(x: float) -> int:
    """Round to whole merchants, halves up."""
    return math.floor(x + 0.5)


def last_entry_day(settings: Settings) -> float:
    """The last day a merchant can enter a segment: the end of the weeks of signups. The run itself
    goes on until the horizon of every segment entered by then has closed."""
    return settings.weeks * DAYS_PER_WEEK


def already_paying(settings: Settings, start: int) -> int:
    """Existing merchants who already pay. They are counted but take no part in the simulation."""
    return _whole(start * settings.already_paying_share)


def weekly_signups(settings: Settings, start: int) -> list[int]:
    """New signups per week: growth falls linearly from the first-week to the last-week rate and
    applies to the merchant base as it stands that week. Each week is rounded to whole merchants
    before it joins the base."""
    base = start
    out: list[int] = []
    for week in range(settings.weeks):
        progress = week / (settings.weeks - 1) if settings.weeks > 1 else 0.0
        growth = settings.growth_first_week + (settings.growth_last_week - settings.growth_first_week) * progress
        new = _whole(base * growth)
        out.append(new)
        base += new
    return out


def existing_by_segment(settings: Settings, start: int) -> dict[Segment, int]:
    """How many existing merchants sit in each segment today (those already paying aren't simulated)."""
    return {s: _whole(start * share) for s, share in settings.existing_shares.items()}


def merchants(settings: Settings, existing: dict[Segment, int], signups: list[int], seed: int) -> list[Merchant]:
    """Every simulated merchant. Existing merchants enter their segment at seeded moments spread over
    the first days of the run; new signups arrive at a seeded moment inside their week and start in
    Idle. A merchant's key (and so every draw made for it) depends only on its own group and place in
    that group, so it doesn't shift when other counts change."""
    out: list[Merchant] = []
    for segment, count in existing.items():
        for k in range(count):
            key = f"existing-{segment.value}-{k}"
            out.append(Merchant(key, settings.existing_spread_days * draw(seed, key, "arrival"), True, segment))
    for week, count in enumerate(signups):
        for k in range(count):
            arrival = DAYS_PER_WEEK * (week + draw(seed, "signup", week, k, "arrival"))
            out.append(Merchant(f"signup-w{week}-{k}", arrival, False, Segment.IDLE))
    return out
