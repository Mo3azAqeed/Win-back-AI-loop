"""Merchants moving through Idle → Drafter → Trialist → paid, with or without the hand-written emails.

Every approach runs on one shared calendar: all merchants' events (entering a segment, an email
falling due, a goal action) are processed strictly in date order, so anything that learns from
outcomes can only ever see what has already happened.
"""

import heapq
import itertools
import math
from dataclasses import dataclass, field
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


class _Event(Enum):
    ENTER = 0
    GOAL = 1
    EMAIL_DUE = 2


@dataclass
class _OpenStay:
    """A stay still in progress: its goal action and email can still change."""

    segment: Segment
    entered: float
    deadline: float
    draws: _Draws
    goal_day: float | None = None
    goal_id: int | None = None  # which scheduled goal action is the live one; earlier ones are stale
    email: EmailFate = EmailFate.NOT_PLANNED
    email_due: float | None = None
    email_sent_at: float | None = None

    @property
    def email_pending(self) -> bool:
        return self.email_due is not None and self.email is EmailFate.NOT_PLANNED

    def close(self, left: float | None) -> Stay:
        """Settle the stay. An email still pending was skipped if the merchant moved on before it was
        due; if the run ended first, it was never sent and counts as not planned."""
        email = self.email
        if self.email_pending and left is not None and self.email_due is not None and left < self.email_due:
            email = EmailFate.SKIPPED
        return Stay(self.segment, self.entered, left, email, self.email_sent_at)


@dataclass
class _MerchantState:
    merchant: Merchant
    stays: list[Stay] = field(default_factory=list)
    open: _OpenStay | None = None
    last_email: float = -math.inf
    paid_at: float | None = None


class _Calendar:
    """One approach's run: every merchant's events on one timeline, handled in date order."""

    def __init__(self, settings: Settings, merchants: list[Merchant], seed: int, approach: Approach) -> None:
        self.settings, self.seed, self.approach = settings, seed, approach
        self.end = simulation_end(settings)
        self.merchants = [_MerchantState(m) for m in merchants]
        self.queue: list[tuple[float, int, _Event, int, int]] = []
        self.order = itertools.count()
        self.event_days: list[float] = []
        for i, m in enumerate(merchants):
            self._schedule(m.arrival_day, _Event.ENTER, i)

    def _schedule(self, day: float, event: _Event, merchant: int, goal_id: int = -1) -> None:
        if day <= self.end:
            heapq.heappush(self.queue, (day, next(self.order), event, merchant, goal_id))

    def run(self) -> tuple[list[Journey], list[float]]:
        while self.queue:
            day, _, event, i, goal_id = heapq.heappop(self.queue)
            self.event_days.append(day)
            state = self.merchants[i]
            if event is _Event.ENTER:
                self._enter(state, i, state.merchant.start_segment, day)
            elif event is _Event.EMAIL_DUE:
                self._email_due(state, i, day)
            elif state.open is not None and goal_id == state.open.goal_id:
                self._goal(state, i, day)
        journeys = []
        for state in self.merchants:
            if state.open is not None:
                state.stays.append(state.open.close(None))
            journeys.append(Journey(state.merchant, tuple(state.stays), state.paid_at))
        return journeys, self.event_days

    def _enter(self, state: _MerchantState, i: int, segment: Segment, day: float) -> None:
        behaviour = self.settings.segments[segment]
        deadline = day + self.settings.trial_days if segment is Segment.TRIALIST else math.inf
        stay = _OpenStay(segment, day, deadline, _Draws(self.seed, state.merchant, segment))
        state.open = stay
        if stay.draws.chance("organic") < behaviour.organic_share:
            organic = day + stay.draws.wait_days("organic_time", behaviour.organic_mean_days)
            if organic <= deadline:
                self._set_goal(stay, i, organic)
        if self.approach is Approach.HAND_WRITTEN:
            self._plan_email(state, i, stay, day)

    def _plan_email(self, state: _MerchantState, i: int, stay: _OpenStay, day: float) -> None:
        """The one send path: every email is planned here and then sent or skipped on its due day."""
        behaviour = self.settings.segments[stay.segment]
        due = max(day + behaviour.hand_written_after_days, state.last_email + self.settings.min_gap_days)
        stay.email_due = due
        if due > stay.deadline:
            stay.email = EmailFate.SKIPPED
        else:
            self._schedule(due, _Event.EMAIL_DUE, i)

    def _email_due(self, state: _MerchantState, i: int, day: float) -> None:
        stay = state.open
        if stay is None or stay.email_due != day or not stay.email_pending:
            return  # the merchant moved on before the email was due
        behaviour = self.settings.segments[stay.segment]
        stay.email, stay.email_sent_at, state.last_email = EmailFate.SENT, day, day
        read = stay.draws.chance("read") < _shifted(behaviour.read_rate, FIRST_DRAFT.subject_appeal)
        clicked = read and stay.draws.chance("click") < _shifted(behaviour.click_rate, FIRST_DRAFT.body_appeal)
        if clicked and stay.draws.chance("act") < behaviour.act_rate:
            prompted = day + stay.draws.wait_days("response", behaviour.response_mean_days)
            if prompted <= stay.deadline and (stay.goal_day is None or prompted < stay.goal_day):
                self._set_goal(stay, i, prompted)

    def _set_goal(self, stay: _OpenStay, i: int, day: float) -> None:
        stay.goal_day, stay.goal_id = day, next(self.order)
        self._schedule(day, _Event.GOAL, i, stay.goal_id)

    def _goal(self, state: _MerchantState, i: int, day: float) -> None:
        assert state.open is not None
        state.stays.append(state.open.close(day))
        following = NEXT_SEGMENT[state.open.segment]
        state.open = None
        if following is None:
            state.paid_at = day
        else:
            self._enter(state, i, following, day)


def run_calendar(settings: Settings, merchants: list[Merchant], seed: int, approach: Approach) -> tuple[list[Journey], list[float]]:
    """Run one approach for every merchant on one shared calendar. Returns the journeys and the
    days of every event handled, in the order they were handled."""
    return _Calendar(settings, merchants, seed, approach).run()


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
    """Idle merchants counted over the Idle horizon (a fixed number of days from entering Idle), for each approach.
    The run lasts long enough for every Idle merchant's horizon to close."""
    horizon = settings.segments[Segment.IDLE].horizon_days
    counted = {approach: [j.stays[0] for j in js if j.stays[0].segment is Segment.IDLE] for approach, js in journeys.items()}
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
