"""Replaying the same weeks with different luck, keeping only what the report needs from each replay."""

import math
import statistics
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
    """Every replay from one starting size, and what they add up to. Lifts are in points."""

    seeds: list[int]
    stats: list[ReplayStats]

    def lifts(self, segment: Segment, approach: Approach) -> list[float]:
        return [s.lifts[segment][approach] * 100 for s in self.stats]

    def average(self, segment: Segment, approach: Approach) -> float:
        return statistics.fmean(self.lifts(segment, approach))

    def middle_90(self, segment: Segment, approach: Approach) -> tuple[float, float]:
        """Where the middle 90% of replays fall: from the 5th to the 95th percentile."""
        values = self.lifts(segment, approach)
        if len(values) < 2:
            return values[0], values[0]
        cuts = statistics.quantiles(values, n=20, method="inclusive")
        return cuts[0], cuts[-1]

    def wins(self, segment: Segment) -> int:
        """Replays where the AI loop lifted more than the hand-written email."""
        return sum(a > h for a, h in zip(self.lifts(segment, Approach.AI_LOOP), self.lifts(segment, Approach.HAND_WRITTEN)))

    def ties(self, segment: Segment) -> int:
        """Replays where both lifted exactly as much: with the same merchants and luck, an AI loop that
        sends the same email at the same time gets the same result."""
        return sum(a == h for a, h in zip(self.lifts(segment, Approach.AI_LOOP), self.lifts(segment, Approach.HAND_WRITTEN)))

    def weekly(self, segment: Segment, approach: Approach) -> list[float]:
        """The average across replays of the true lift so far at the end of each week."""
        weeks = len(self.stats[0].weekly[segment][approach])
        return [statistics.fmean(s.weekly[segment][approach][w] * 100 for s in self.stats) for w in range(weeks)]

    def ahead_from(self, segment: Segment) -> int | None:
        """The week from which the AI loop's average lift so far stays above the hand-written email's, if any."""
        ai, hand = self.weekly(segment, Approach.AI_LOOP), self.weekly(segment, Approach.HAND_WRITTEN)
        week = None
        for w in range(len(ai), 0, -1):
            if ai[w - 1] <= hand[w - 1]:
                break
            week = w
        return week

    def did_better(self, segment: Segment) -> bool:
        """Higher average true lift, and ahead in more than half of the replays."""
        return self.average(segment, Approach.AI_LOOP) > self.average(segment, Approach.HAND_WRITTEN) and self.wins(segment) * 2 > len(self.stats)

    def revenue(self, approach: Approach) -> float:
        """Average Trialist first-month revenue per replay."""
        return statistics.fmean(s.revenue[approach] for s in self.stats)


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
