"""The made-up merchants: who exists and when they arrive."""

import math
from dataclasses import dataclass

from winback.draws import draw
from winback.settings import Settings


@dataclass(frozen=True)
class Merchant:
    id: int
    arrival_day: float
    existing: bool


def already_paying(settings: Settings) -> int:
    """Today's merchants who already pay. They are counted but take no part in the simulation."""
    return math.floor(settings.start_merchants * settings.already_paying_share + 0.5)


def weekly_signups(settings: Settings) -> list[int]:
    """New signups per week: growth falls linearly from the first-week to the last-week rate,
    applied each week to the merchant base as it stands that week."""
    base = settings.start_merchants
    out: list[int] = []
    for week in range(settings.weeks):
        share = week / (settings.weeks - 1) if settings.weeks > 1 else 0.0
        growth = settings.growth_first_week + (settings.growth_last_week - settings.growth_first_week) * share
        new = math.floor(base * growth + 0.5)
        out.append(new)
        base += new
    return out


def merchants(settings: Settings, seed: int) -> list[Merchant]:
    """Every simulated merchant: today's merchants who don't pay yet, then each week's signups,
    each arriving at a seeded moment inside their week."""
    out = [Merchant(i, 0.0, True) for i in range(settings.start_merchants - already_paying(settings))]
    for week, count in enumerate(weekly_signups(settings)):
        for _ in range(count):
            i = len(out)
            out.append(Merchant(i, 7 * week + 7 * draw(seed, i, "arrival"), False))
    return out
