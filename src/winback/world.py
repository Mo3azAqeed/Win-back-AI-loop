"""The made-up merchants: who exists and when they arrive."""

import math
from dataclasses import dataclass

from winback.draws import draw
from winback.settings import Settings

DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class Merchant:
    id: int
    key: str
    arrival_day: float
    existing: bool


def _whole(x: float) -> int:
    """Round to whole merchants, halves up."""
    return math.floor(x + 0.5)


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


def merchants(existing_simulated: int, signups: list[int], seed: int) -> list[Merchant]:
    """Every simulated merchant: existing merchants who don't pay yet, then each week's new signups,
    each arriving at a seeded moment inside their week. A merchant's key (and so every draw made for
    it) depends on its week and its place in that week, not on how many existing merchants there are."""
    out = [Merchant(i, f"existing-{i}", 0.0, True) for i in range(existing_simulated)]
    for week, count in enumerate(signups):
        for k in range(count):
            arrival = DAYS_PER_WEEK * (week + draw(seed, "signup", week, k, "arrival"))
            out.append(Merchant(len(out), f"signup-w{week}-{k}", arrival, False))
    return out
