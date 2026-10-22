"""Merchants moving through Idle → Drafter → Trialist → paid, with or without the hand-written emails."""

import math
from dataclasses import dataclass
from enum import Enum

from winback.draws import draw
from winback.settings import SegmentSettings, Settings
from winback.world import Merchant, Segment, simulation_end

NEXT = {Segment.IDLE: Segment.DRAFTER, Segment.DRAFTER: Segment.TRIALIST, Segment.TRIALIST: Segment.PAID}


class Approach(Enum):
    NO_EMAIL = "no_email"
    HAND_WRITTEN = "hand_written"


class EmailFate(Enum):
    NOT_PLANNED = "not planned"
    SENT = "sent"
    SKIPPED = "skipped"  # the merchant moved on before the email was due


@dataclass(frozen=True)
class EmailCopy:
    """An email's hidden appeal, as a shift on the log-odds of reading (subject) and clicking (body).
    Your first draft is the reference: 0, shown as hidden quality 100."""

    subject_appeal: float = 0.0
    body_appeal: float = 0.0


FIRST_DRAFT = EmailCopy()


@dataclass(frozen=True)
class Stay:
    """One merchant's time in one segment. `left` is when it took the goal action (None if not by the end)."""

    segment: Segment
    entered: float
    left: float | None
    email: EmailFate
    email_sent_at: float | None


@dataclass(frozen=True)
class Journey:
    merchant: Merchant
    stays: tuple[Stay, ...]


def _shifted(rate: float, appeal: float) -> float:
    """A reference chance moved by a hidden appeal on the log-odds scale.
    A certain or impossible chance stays so, whatever the appeal."""
    if rate <= 0.0 or rate >= 1.0:
        return rate
    return 1 / (1 + math.exp(-(math.log(rate / (1 - rate)) + appeal)))


class _Draws:
    """The seeded draws for one merchant in one segment, the same whichever approach is used."""

    def __init__(self, seed: int, merchant: Merchant, segment: Segment) -> None:
        self.seed, self.key, self.segment = seed, merchant.key, segment.value

    def chance(self, purpose: str) -> float:
        return draw(self.seed, self.key, self.segment, purpose)

    def wait_days(self, purpose: str, mean_days: float) -> float:
        return -mean_days * math.log(1.0 - self.chance(purpose))


def _behaviour(settings: Settings, segment: Segment) -> SegmentSettings:
    return {Segment.IDLE: settings.idle, Segment.DRAFTER: settings.drafter, Segment.TRIALIST: settings.trialist}[segment]


def journey(settings: Settings, m: Merchant, seed: int, approach: Approach, copy: EmailCopy = FIRST_DRAFT) -> Journey:
    """Follow one merchant from its first segment until it pays or the run ends."""
    end = simulation_end(settings)
    stays: list[Stay] = []
    segment, entered, last_email = m.start_segment, m.arrival_day, -math.inf
    while segment is not Segment.PAID and entered <= end:
        b, d = _behaviour(settings, segment), _Draws(seed, m, segment)
        deadline = entered + settings.trial_days if segment is Segment.TRIALIST else math.inf
        step: float | None = None
        if d.chance("organic") < b.organic_share:
            step = entered + d.wait_days("organic_time", b.organic_mean_days)
        if step is not None and step > deadline:
            step = None
        fate, sent_at = EmailFate.NOT_PLANNED, None
        if approach is Approach.HAND_WRITTEN:
            due = max(entered + b.hand_written_after_days, last_email + settings.min_gap_days)
            if (step is not None and step < due) or due > deadline:
                fate = EmailFate.SKIPPED
            elif due <= end:
                fate, sent_at, last_email = EmailFate.SENT, due, due
                read = d.chance("read") < _shifted(b.read_rate, copy.subject_appeal)
                clicked = read and d.chance("click") < _shifted(b.click_rate, copy.body_appeal)
                if clicked and d.chance("act") < b.act_rate:
                    prompted = due + d.wait_days("response", b.response_mean_days)
                    if prompted <= deadline:
                        step = prompted if step is None else min(step, prompted)
        left = step if step is not None and step <= end else None
        stays.append(Stay(segment, entered, left, fate, sent_at))
        if left is None:
            break
        segment, entered = NEXT[segment], left
    if segment is Segment.PAID:
        stays.append(Stay(Segment.PAID, entered, None, EmailFate.NOT_PLANNED, None))
    return Journey(m, tuple(stays))


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


@dataclass(frozen=True)
class SegmentTraffic:
    entered: int
    sent: int
    skipped: int


def idle_outcomes(settings: Settings, journeys: dict[Approach, list[Journey]]) -> dict[Approach, SegmentOutcome]:
    """Idle merchants counted over a fixed horizon from entering Idle, for each approach."""
    end, horizon = simulation_end(settings), settings.idle_horizon_days
    tallies: dict[Approach, tuple[int, int, int, int]] = {}
    for approach, js in journeys.items():
        firsts = [j.stays[0] for j in js if j.stays and j.stays[0].segment is Segment.IDLE and j.stays[0].entered + horizon <= end]
        reached = sum(s.left is not None and s.left <= s.entered + horizon for s in firsts)
        sent = sum(s.email is EmailFate.SENT for s in firsts)
        skipped = sum(s.email is EmailFate.SKIPPED for s in firsts)
        tallies[approach] = (len(firsts), reached, sent, skipped)
    baseline = _rate(tallies[Approach.NO_EMAIL][1], tallies[Approach.NO_EMAIL][0])
    return {a: SegmentOutcome(n, r, s, k, _rate(r, n) - baseline) for a, (n, r, s, k) in tallies.items()}


def traffic(journeys: list[Journey]) -> dict[Segment, SegmentTraffic]:
    """Per segment: merchants who entered it, emails sent there, and emails skipped because the merchant moved on."""
    out = {}
    for segment in (Segment.IDLE, Segment.DRAFTER, Segment.TRIALIST):
        stays = [s for j in journeys for s in j.stays if s.segment is segment]
        out[segment] = SegmentTraffic(
            len(stays), sum(s.email is EmailFate.SENT for s in stays), sum(s.email is EmailFate.SKIPPED for s in stays)
        )
    return out
