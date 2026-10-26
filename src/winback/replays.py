"""Replaying the same weeks with different luck, keeping only what the report needs from each replay."""

import math
from dataclasses import dataclass

from winback.draws import draw
from winback.lifecycle import Approach
from winback.segments import Segment
from winback.settings import Settings
from winback.world import DAYS_PER_WEEK

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # run.py imports this module
    from winback.run import StartResult


def replay_seed(seed: int, replay: int) -> int:
    """The first replay is the seed itself, so it matches a single run; the others get seeds drawn from it."""
    return seed if replay == 0 else int(draw(seed, "replay", replay) * 2**31)


@dataclass(frozen=True)
class ReplayStats:
    """One replay's true lift per segment and approach, its true lift so far week by week, and its Trialist
    first-month revenue per approach."""

    lifts: dict[Segment, dict[Approach, float]]
    weekly: dict[Segment, dict[Approach, list[float]]]
    revenue: dict[Approach, float]


@dataclass(frozen=True)
class Replays:
    seeds: list[int]
    stats: list[ReplayStats]


def replay_stats(start: "StartResult", settings: Settings) -> ReplayStats:
    """True lift so far, at the end of each week, counts the same merchants true lift does (the emailed ones
    who would be in the segment with no email) whose result was known by then: their horizon, counted from
    when they would have entered with no email, had closed. That is all the AI loop could have learned from
    by then. The weeks run until the last signup's horizon closes, where it is the segment's true lift."""
    lifts = {s: {a: o.true_lift for a, o in by_approach.items()} for s, by_approach in start.outcomes.items()}
    revenue = {a: o.first_month_revenue for a, o in start.outcomes[Segment.TRIALIST].items()}
    longest = max(b.horizon_days for b in settings.segments.values())
    weeks = math.ceil((settings.weeks * DAYS_PER_WEEK + longest) / DAYS_PER_WEEK)
    weekly: dict[Segment, dict[Approach, list[float]]] = {}
    for segment in Segment:
        known_on = {r.merchant_key: r.known_on for r in start.results[Approach.NO_EMAIL] if r.segment is segment and not r.holdout}
        reached = {a: {r.merchant_key: r.reached for r in results if r.segment is segment and r.merchant_key in known_on} for a, results in start.results.items()}
        weekly[segment] = {a: [] for a in Approach}
        for week in range(1, weeks + 1):
            judged = [key for key, day in known_on.items() if day <= week * DAYS_PER_WEEK]
            share = {a: sum(reached[a][key] for key in judged) / len(judged) if judged else 0.0 for a in Approach}
            for a in Approach:
                weekly[segment][a].append(share[a] - share[Approach.NO_EMAIL])
    return ReplayStats(lifts, weekly, revenue)
