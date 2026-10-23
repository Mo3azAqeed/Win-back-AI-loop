"""The single entry point for running a simulation."""

from dataclasses import dataclass

from winback import report
from winback.lifecycle import Approach, EmailResult, Journey, SegmentOutcome, StayResult, holdout_baselines, run_calendar, segment_outcomes
from winback.loop import LoopReport
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
    outcomes: dict[Segment, dict[Approach, SegmentOutcome]]  # emailed merchants only
    baselines: dict[Segment, SegmentOutcome]  # the holdout, never emailed
    loop: LoopReport  # what the AI loop tried and where it stands at the end


@dataclass(frozen=True)
class RunResult:
    by_start: dict[int, StartResult]
    report: str


def run_simulation(settings: Settings, seed: int) -> RunResult:
    """Run the simulation once for each starting size in the settings and write one report."""
    by_start = {start: _run_from(settings, start, seed) for start in settings.start_sizes}
    return RunResult(by_start=by_start, report=report.render(settings, seed, by_start))


def _run_from(settings: Settings, start: int, seed: int) -> StartResult:
    paying = already_paying(settings, start)
    signups = weekly_signups(settings, start)
    existing = existing_by_segment(settings, start)
    simulated = merchants(settings, existing, signups, seed)
    calendars = {a: run_calendar(settings, simulated, seed, a) for a in Approach}
    journeys = {a: c.journeys for a, c in calendars.items()}
    results = {a: c.results for a, c in calendars.items()}
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
        outcomes=segment_outcomes(calendars, settings.paid_window_days),
        # A holdout merchant is never emailed, so it behaves the same in every emailing approach.
        baselines=holdout_baselines(calendars[Approach.HAND_WRITTEN], settings.paid_window_days),
        loop=_loop_report(calendars[Approach.AI_LOOP].loop),
    )


def _loop_report(report: LoopReport | None) -> LoopReport:
    assert report is not None, "the AI loop's run always has a loop report"
    return report
