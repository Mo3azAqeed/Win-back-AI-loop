"""Merchants moving through Idle → Drafter → Trialist → paid, with or without the hand-written emails."""

import math
from dataclasses import dataclass
from enum import Enum

from winback.draws import draw
from winback.segments import NEXT_SEGMENT, Segment
from winback.settings import Settings
from winback.world import Merchant, simulation_end


class Approach(Enum):
    NO_EMAIL = "no_email"
    HAND_WRITTEN = "hand_written"


class EmailFate(Enum):
    NOT_PLANNED = "not planned"
    SENT = "sent"
    SKIPPED = "skipped"  # the merchant moved on, or the trial ended, before the email was due


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
    paid_at: float | None


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


def _stay(settings: Settings, merchant: Merchant, seed: int, approach: Approach, segment: Segment, entered: float, last_email: float) -> Stay:
    """One merchant's time in one segment: when it takes the goal action, and what happens to its email."""
    behaviour, draws, end = settings.segments[segment], _Draws(seed, merchant, segment), simulation_end(settings)
    deadline = entered + settings.trial_days if segment is Segment.TRIALIST else math.inf
    goal_day: float | None = None
    if draws.chance("organic") < behaviour.organic_share:
        goal_day = entered + draws.wait_days("organic_time", behaviour.organic_mean_days)
    if goal_day is not None and goal_day > deadline:
        goal_day = None
    fate, sent_at = EmailFate.NOT_PLANNED, None
    if approach is Approach.HAND_WRITTEN:
        due = max(entered + behaviour.hand_written_after_days, last_email + settings.min_gap_days)
        moved_on_first = goal_day is not None and goal_day < due and goal_day <= end
        if moved_on_first or due > deadline:
            fate = EmailFate.SKIPPED
        elif due <= end:
            fate, sent_at = EmailFate.SENT, due
            read = draws.chance("read") < _shifted(behaviour.read_rate, FIRST_DRAFT.subject_appeal)
            clicked = read and draws.chance("click") < _shifted(behaviour.click_rate, FIRST_DRAFT.body_appeal)
            if clicked and draws.chance("act") < behaviour.act_rate:
                prompted = due + draws.wait_days("response", behaviour.response_mean_days)
                if prompted <= deadline:
                    goal_day = prompted if goal_day is None else min(goal_day, prompted)
    left = goal_day if goal_day is not None and goal_day <= end else None
    return Stay(segment, entered, left, fate, sent_at)


def journey(settings: Settings, merchant: Merchant, seed: int, approach: Approach) -> Journey:
    """Follow one merchant from its first segment until it pays or the run ends."""
    stays: list[Stay] = []
    segment: Segment | None = merchant.start_segment
    entered, last_email = merchant.arrival_day, -math.inf
    while segment is not None:
        stay = _stay(settings, merchant, seed, approach, segment, entered, last_email)
        stays.append(stay)
        if stay.email_sent_at is not None:
            last_email = stay.email_sent_at
        if stay.left is None:
            return Journey(merchant, tuple(stays), None)
        segment, entered = NEXT_SEGMENT[segment], stay.left
    return Journey(merchant, tuple(stays), entered)


def _rate(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


@dataclass(frozen=True)
class EmailTally:
    sent: int
    skipped: int


def _emails(stays: list[Stay]) -> EmailTally:
    """Emails sent and emails skipped across these stays."""
    return EmailTally(sum(s.email is EmailFate.SENT for s in stays), sum(s.email is EmailFate.SKIPPED for s in stays))


@dataclass(frozen=True)
class SegmentOutcome:
    counted: int
    reached: int
    emails: EmailTally
    true_lift: float

    @property
    def reached_share(self) -> float:
        return _rate(self.reached, self.counted)


@dataclass(frozen=True)
class SegmentTraffic:
    entered: int
    emails: EmailTally


def idle_outcomes(settings: Settings, journeys: dict[Approach, list[Journey]]) -> dict[Approach, SegmentOutcome]:
    """Idle merchants counted over the Idle horizon (a fixed number of days from entering Idle), for each approach."""
    end, horizon = simulation_end(settings), settings.idle_horizon_days
    counted: dict[Approach, list[Stay]] = {
        approach: [j.stays[0] for j in js if j.stays[0].segment is Segment.IDLE and j.stays[0].entered + horizon <= end]
        for approach, js in journeys.items()
    }
    reached = {a: sum(s.left is not None and s.left <= s.entered + horizon for s in stays) for a, stays in counted.items()}
    no_email_share = _rate(reached[Approach.NO_EMAIL], len(counted[Approach.NO_EMAIL]))
    return {
        a: SegmentOutcome(len(stays), reached[a], _emails(stays), _rate(reached[a], len(stays)) - no_email_share)
        for a, stays in counted.items()
    }


def traffic(journeys: list[Journey]) -> dict[Segment, SegmentTraffic]:
    """Per segment: merchants who entered it, and the emails sent and skipped there."""
    out = {}
    for segment in Segment:
        stays = [s for j in journeys for s in j.stays if s.segment is segment]
        out[segment] = SegmentTraffic(len(stays), _emails(stays))
    return out
