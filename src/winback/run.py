"""The single entry point for running a simulation."""

from dataclasses import dataclass

from winback import report
from winback.lifecycle import Approach, EmailResult, Journey, OfferSummary, SegmentOutcome, StayResult, offer_summary, run_calendar, segment_outcomes
from winback.loop import LoopReport
from winback.replays import Replays, replay_seed, replay_stats
from winback.settings import Settings
from winback.segments import Segment
from winback.world import Merchant, already_paying, existing_by_segment, merchants, weekly_signups


@dataclass(frozen=True)
class StartResult:
    """One run of the simulation from one starting number of merchants."""

    existing_merchants: int
    already_paying: int
    existing_simulated: int
    weekly_signups: list[int]
    merchants: list[Merchant]
    journeys: dict[Approach, list[Journey]]
    results: dict[Approach, list[StayResult]]
    email_results: dict[Approach, list[EmailResult]]
    event_days: dict[Approach, list[float]]
    outcomes: dict[Segment, dict[Approach, SegmentOutcome]]  # emailed merchants who would be in the segment with no email
    pushed: dict[Segment, dict[Approach, SegmentOutcome]]  # emailed merchants an earlier email pushed into the segment
    baselines: dict[Segment, SegmentOutcome]  # the holdout, never emailed
    loop: LoopReport  # what the AI loop tried and where it stands at the end
    offers: OfferSummary  # the AI loop's Trialist offers


@dataclass(frozen=True)
class RunResult:
    by_start: dict[int, StartResult]  # the first replay in full: the seed itself
    replays: dict[int, Replays]  # every replay, summed up
    report: str


def run_simulation(settings: Settings, seed: int, replays: int = 1) -> RunResult:
    """Replay the weeks this many times with different luck, from each starting size in the settings, and
    write one report: what happened across the replays, then the first replay in full."""
    seeds = [replay_seed(seed, i) for i in range(replays)]
    by_start: dict[int, StartResult] = {}
    summed: dict[int, Replays] = {}
    for start in settings.start_sizes:
        stats = []
        for i, replay in enumerate(seeds):
            result = _run_from(settings, start, replay)
            if i == 0:
                by_start[start] = result
            stats.append(replay_stats(result, settings.weeks))  # only the summary is kept, so memory stays flat
        summed[start] = Replays(seeds, stats)
    return RunResult(by_start=by_start, replays=summed, report=report.render(settings, seed, by_start, summed))


def _run_from(settings: Settings, start: int, seed: int) -> StartResult:
    paying = already_paying(settings, start)
    signups = weekly_signups(settings, start)
    existing = existing_by_segment(settings, start)
    simulated = merchants(settings, existing, signups, seed)
    calendars = {a: run_calendar(settings, simulated, seed, a) for a in Approach}
    journeys = {a: c.journeys for a, c in calendars.items()}
    results = {a: c.results for a, c in calendars.items()}
    outcomes = segment_outcomes(calendars, settings.paid_window_days)
    return StartResult(
        existing_merchants=start,
        already_paying=paying,
        existing_simulated=sum(existing.values()),
        weekly_signups=signups,
        merchants=simulated,
        journeys=journeys,
        results=results,
        email_results={a: c.email_results for a, c in calendars.items()},
        event_days={a: c.event_days for a, c in calendars.items()},
        outcomes=outcomes.judged,
        pushed=outcomes.pushed,
        baselines=outcomes.baselines,
        loop=_loop_report(calendars[Approach.AI_LOOP].loop),
        offers=offer_summary(calendars, settings.monthly_price),
    )


def _loop_report(report: LoopReport | None) -> LoopReport:
    assert report is not None, "the AI loop's run always has a loop report"
    return report
