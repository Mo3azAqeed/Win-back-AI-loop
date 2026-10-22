"""The single entry point for running a simulation (Seam 1)."""

from dataclasses import dataclass

from winback import report
from winback.settings import Settings
from winback.world import Merchant, already_paying, merchants, weekly_signups


@dataclass(frozen=True)
class RunResult:
    weekly_signups: list[int]
    existing_merchants: int
    already_paying: int
    existing_simulated: int
    merchants: list[Merchant]
    report: str


def run_simulation(settings: Settings, seed: int) -> RunResult:
    paying = already_paying(settings)
    signups = weekly_signups(settings)
    return RunResult(
        weekly_signups=signups,
        existing_merchants=settings.start_merchants,
        already_paying=paying,
        existing_simulated=settings.start_merchants - paying,
        merchants=merchants(settings, seed),
        report=report.render(settings, seed, signups, paying),
    )
