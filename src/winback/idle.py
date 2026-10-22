"""Idle merchants: signed up, no store draft yet. Goal action: start a draft."""

import math
from dataclasses import dataclass
from enum import Enum

from winback.draws import draw
from winback.settings import IdleSettings, Settings
from winback.world import Merchant, simulation_end


class Approach(Enum):
    NO_EMAIL = "no_email"
    HAND_WRITTEN = "hand_written"


class EmailFate(Enum):
    NOT_PLANNED = "not planned"
    SENT = "sent"
    SKIPPED = "skipped"  # the merchant started a draft before the email was due


@dataclass(frozen=True)
class EmailCopy:
    """An email's hidden appeal, as a shift on the log-odds of reading (subject) and clicking (body).
    Your first draft is the reference: 0, shown as hidden quality 100."""

    subject_appeal: float = 0.0
    body_appeal: float = 0.0


FIRST_DRAFT = EmailCopy()


def _rate(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


@dataclass(frozen=True)
class SegmentOutcome:
    counted: int
    reached: int
    sent: int
    skipped: int
    true_lift: float

    @property
    def reached_share(self) -> float:
        return _rate(self.reached, self.counted)


def _shifted(rate: float, appeal: float) -> float:
    """A reference chance moved by a hidden appeal on the log-odds scale.
    A certain or impossible chance stays so, whatever the appeal."""
    if rate <= 0.0 or rate >= 1.0:
        return rate
    return 1 / (1 + math.exp(-(math.log(rate / (1 - rate)) + appeal)))


class _Draws:
    """The seeded draws for one Idle merchant, the same whichever approach is used."""

    def __init__(self, seed: int, merchant: Merchant) -> None:
        self.seed, self.key = seed, merchant.key

    def chance(self, purpose: str) -> float:
        return draw(self.seed, self.key, "idle", purpose)

    def wait_days(self, purpose: str, mean_days: float) -> float:
        return -mean_days * math.log(1.0 - self.chance(purpose))


def _draft_day(idle: IdleSettings, m: Merchant, seed: int, copy: EmailCopy | None) -> tuple[float | None, EmailFate]:
    """When the merchant starts a draft (None if never) and what happened to its email."""
    d = _Draws(seed, m)
    drafted = m.arrival_day + d.wait_days("organic_time", idle.organic_mean_days) if d.chance("organic") < idle.organic_share else None
    if copy is None:
        return drafted, EmailFate.NOT_PLANNED
    send = m.arrival_day + idle.hand_written_after_days
    if drafted is not None and drafted < send:
        return drafted, EmailFate.SKIPPED
    read = d.chance("read") < _shifted(idle.read_rate, copy.subject_appeal)
    clicked = read and d.chance("click") < _shifted(idle.click_rate, copy.body_appeal)
    if clicked and d.chance("act") < idle.act_rate:
        prompted = send + d.wait_days("response", idle.response_mean_days)
        drafted = prompted if drafted is None else min(drafted, prompted)
    return drafted, EmailFate.SENT


def idle_outcomes(settings: Settings, merchants: list[Merchant], seed: int) -> dict[Approach, SegmentOutcome]:
    """Score each approach on the same new signups with the same luck."""
    idle, end = settings.idle, simulation_end(settings)
    counted = [m for m in merchants if not m.existing and m.arrival_day + idle.horizon_days <= end]
    tallies: dict[Approach, tuple[int, int, int, int]] = {}
    for approach in Approach:
        copy = FIRST_DRAFT if approach is Approach.HAND_WRITTEN else None
        results = [(_draft_day(idle, m, seed, copy), m) for m in counted]
        reached = sum(day is not None and day <= m.arrival_day + idle.horizon_days for (day, _), m in results)
        sent = sum(fate is EmailFate.SENT for (_, fate), _ in results)
        skipped = sum(fate is EmailFate.SKIPPED for (_, fate), _ in results)
        tallies[approach] = (len(counted), reached, sent, skipped)
    baseline = _rate(tallies[Approach.NO_EMAIL][1], tallies[Approach.NO_EMAIL][0])
    return {a: SegmentOutcome(n, r, s, k, _rate(r, n) - baseline) for a, (n, r, s, k) in tallies.items()}
