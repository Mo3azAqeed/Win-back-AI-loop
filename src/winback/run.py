"""The single entry point for running a simulation."""

from dataclasses import dataclass

from winback import report
from winback.idle import SegmentOutcome, idle_outcomes
from winback.settings import Settings
from winback.world import Merchant, already_paying, merchants, weekly_signups


@dataclass(frozen=True)
class StartResult:
    """One run of the simulation from one starting number of merchants."""

    existing_merchants: int
    already_paying: int
    existing_simulated: int
    weekly_signups: list[int]
    merchants: list[Merchant]
    idle: dict[str, SegmentOutcome]


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
    simulated = merchants(start - paying, signups, seed)
    return StartResult(
        existing_merchants=start,
        already_paying=paying,
        existing_simulated=start - paying,
        weekly_signups=signups,
        merchants=simulated,
        idle=idle_outcomes(settings, simulated, seed),
    )
