"""The single entry point for running a simulation."""

from dataclasses import dataclass

from winback import report
from winback.copywriter import Copywriter, StandIn
from winback.lifecycle import Approach, EmailResult, Journey, StayResult, run_calendar
from winback.loop import LoopReport
from winback.outcomes import OfferSummary, SegmentOutcome, offer_summary, segment_outcomes
from winback.replays import Replays, replay_seed, replay_stats
from winback.segments import Segment
from winback.settings import Settings
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


def run_simulation(settings: Settings, seed: int, replays: int | None = 1, copywriter: Copywriter | None = None) -> RunResult:
    """Replay the weeks this many times with different luck, from each starting size in the settings, and
    write one report: what happened across the replays, then the first replay in full. `None` replays as
    many times as the settings say; the default of one is the quick run tests use. The AI loop's new words
    come from the copywriter, shared by every replay; without one, from the stand-in writer's list."""
    copywriter = copywriter or StandIn(settings)
    if replays is None:
        replays = settings.replays
    if replays < 1:
        raise ValueError(f"A run needs at least one replay, not {replays}")
    seeds = [replay_seed(seed, i) for i in range(replays)]
    by_start: dict[int, StartResult] = {}
    replayed: dict[int, Replays] = {}
    for start in settings.start_sizes:
        stats = []
        for i, this_seed in enumerate(seeds):
            result = _run_from(settings, start, this_seed, copywriter)
            if i == 0:
                by_start[start] = result
            stats.append(replay_stats(result.outcomes, result.results, settings))  # only the summary is kept, so memory stays flat
        replayed[start] = Replays(seeds, stats)
    return RunResult(by_start=by_start, replays=replayed, report=report.render(settings, seed, by_start, replayed, copywriter.summary()))


def _run_from(settings: Settings, start: int, seed: int, copywriter: Copywriter) -> StartResult:
    paying = already_paying(settings, start)
    signups = weekly_signups(settings, start)
    existing = existing_by_segment(settings, start)
    simulated = merchants(settings, existing, signups, seed)
    calendars = {a: run_calendar(settings, simulated, seed, a, copywriter) for a in Approach}
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
        offers=offer_summary(calendars),
    )


def _loop_report(report: LoopReport | None) -> LoopReport:
    assert report is not None, "the AI loop's run always has a loop report"
    return report
