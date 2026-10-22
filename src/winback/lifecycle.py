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
from winback.world import Merchant, last_entry_day


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
    # On the same day, an email falling due is handled before a goal action, then a horizon closing.
    EMAIL_DUE = 0
    GOAL = 1
    ENTER = 2
    HORIZON_CLOSES = 3


@dataclass(order=True)
class _Scheduled:
    day: float
    event_order: int
    sequence: int
    event: _Event = field(compare=False)
    merchant: int = field(compare=False)
    stay: "_OpenStay | None" = field(compare=False, default=None)


@dataclass(frozen=True)
class StayResult:
    """What a stay achieved, known on the day its horizon closes (and never before)."""

    merchant_key: str
    segment: Segment
    entered: float
    known_on: float
    goal_day: float | None
    reached: bool


@dataclass
class _OpenStay:
    """One merchant's stay in one segment while the run is going."""

    segment: Segment
    entered: float
    deadline: float
    draws: _Draws
    left: float | None = None
    goal_day: float | None = None
    email: EmailFate = EmailFate.NOT_PLANNED
    email_sent_at: float | None = None

    def freeze(self) -> Stay:
        return Stay(self.segment, self.entered, self.left, self.email, self.email_sent_at)


@dataclass
class _MerchantState:
    index: int
    merchant: Merchant
    stays: list[_OpenStay] = field(default_factory=list)
    last_email: float = -math.inf
    paid_at: float | None = None

    @property
    def current(self) -> _OpenStay | None:
        return self.stays[-1] if self.stays and self.stays[-1].left is None else None


@dataclass(frozen=True)
class CalendarRun:
    journeys: list[Journey]
    results: list[StayResult]  # in the order they became known
    event_days: list[float]  # the day of every event, in the order handled


class _Calendar:
    """One approach's run: every merchant's events on one timeline, handled in date order.

    Merchants enter segments during the weeks of signups; the run then keeps going until the
    horizon of the last segment entered in those weeks has closed."""

    def __init__(self, settings: Settings, merchants: list[Merchant], seed: int, approach: Approach) -> None:
        self.settings, self.seed, self.approach = settings, seed, approach
        self.last_entry_day = last_entry_day(settings)
        self.last_horizon_close = self.last_entry_day
        self.merchants = [_MerchantState(i, m) for i, m in enumerate(merchants)]
        self.queue: list[_Scheduled] = []
        self.sequence = itertools.count()
        self.results: list[StayResult] = []
        self.event_days: list[float] = []
        for state in self.merchants:
            self._schedule(state, state.merchant.arrival_day, _Event.ENTER)

    def _schedule(self, state: _MerchantState, day: float, event: _Event, stay: _OpenStay | None = None) -> None:
        heapq.heappush(self.queue, _Scheduled(day, event.value, next(self.sequence), event, state.index, stay))

    def run(self) -> CalendarRun:
        while self.queue and self.queue[0].day <= max(self.last_entry_day, self.last_horizon_close):
            item = heapq.heappop(self.queue)
            self.event_days.append(item.day)
            state = self.merchants[item.merchant]
            if item.event is _Event.ENTER:
                self._enter(state, state.merchant.start_segment, item.day)
            elif item.event is _Event.EMAIL_DUE and item.stay is not None:
                self._email_due(state, item.stay, item.day)
            elif item.event is _Event.GOAL and item.stay is not None and item.stay.left is None:
                # A goal event belongs to its own stay, and only the earliest one ends it.
                self._reach_goal(state, item.stay, item.day)
            elif item.event is _Event.HORIZON_CLOSES and item.stay is not None:
                self._close_horizon(state, item.stay, item.day)
        journeys = [Journey(s.merchant, tuple(stay.freeze() for stay in s.stays), s.paid_at) for s in self.merchants]
        return CalendarRun(journeys, self.results, self.event_days)

    def _enter(self, state: _MerchantState, segment: Segment, day: float) -> None:
        if day > self.last_entry_day:
            return  # the weeks of signups are over: nobody enters a new segment
        behaviour = self.settings.segments[segment]
        deadline = day + self.settings.trial_days if segment is Segment.TRIALIST else math.inf
        stay = _OpenStay(segment, day, deadline, _Draws(self.seed, state.merchant, segment))
        state.stays.append(stay)
        closes = day + behaviour.horizon_days
        self.last_horizon_close = max(self.last_horizon_close, closes)
        self._schedule(state, closes, _Event.HORIZON_CLOSES, stay)
        if stay.draws.chance("organic") < behaviour.organic_share:
            organic = day + stay.draws.wait_days("organic_time", behaviour.organic_mean_days)
            if organic <= deadline:
                self._set_goal(state, stay, organic)
        if self.approach is Approach.HAND_WRITTEN:
            due = max(day + behaviour.hand_written_after_days, state.last_email + self.settings.min_gap_days)
            self._schedule(state, due, _Event.EMAIL_DUE, stay)

    def _email_due(self, state: _MerchantState, stay: _OpenStay, day: float) -> None:
        """The one send path: on its due day an email is sent, or skipped if the merchant moved on
        or the trial ended."""
        if stay.left is not None or day > stay.deadline:
            stay.email = EmailFate.SKIPPED
            return
        behaviour = self.settings.segments[stay.segment]
        stay.email, stay.email_sent_at, state.last_email = EmailFate.SENT, day, day
        read = stay.draws.chance("read") < _shifted(behaviour.read_rate, FIRST_DRAFT.subject_appeal)
        clicked = read and stay.draws.chance("click") < _shifted(behaviour.click_rate, FIRST_DRAFT.body_appeal)
        if clicked and stay.draws.chance("act") < behaviour.act_rate:
            prompted = day + stay.draws.wait_days("response", behaviour.response_mean_days)
            if prompted <= stay.deadline and (stay.goal_day is None or prompted < stay.goal_day):
                self._set_goal(state, stay, prompted)

    def _set_goal(self, state: _MerchantState, stay: _OpenStay, day: float) -> None:
        stay.goal_day = day
        self._schedule(state, day, _Event.GOAL, stay)

    def _reach_goal(self, state: _MerchantState, stay: _OpenStay, day: float) -> None:
        stay.left = day
        following = NEXT_SEGMENT[stay.segment]
        if following is None:
            state.paid_at = day
        else:
            self._enter(state, following, day)

    def _close_horizon(self, state: _MerchantState, stay: _OpenStay, day: float) -> None:
        reached = stay.left is not None  # events run in date order, so any goal so far is inside the horizon
        self.results.append(StayResult(state.merchant.key, stay.segment, stay.entered, day, stay.left, reached))


def run_calendar(settings: Settings, merchants: list[Merchant], seed: int, approach: Approach) -> CalendarRun:
    """Run one approach for every merchant on one shared calendar."""
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


def segment_outcomes(results: dict[Approach, list[StayResult]], journeys: dict[Approach, list[Journey]]) -> dict[Segment, dict[Approach, SegmentOutcome]]:
    """Per segment and approach: the stays counted, how many reached the goal action within the
    horizon, the emails, and true lift against no email."""
    out: dict[Segment, dict[Approach, SegmentOutcome]] = {}
    for segment in Segment:
        reached = {a: [r.reached for r in rs if r.segment is segment] for a, rs in results.items()}
        no_email_share = _rate(sum(reached[Approach.NO_EMAIL]), len(reached[Approach.NO_EMAIL]))
        out[segment] = {
            a: SegmentOutcome(
                len(r),
                sum(r),
                _emails([s for j in journeys[a] for s in j.stays if s.segment is segment]),
                _rate(sum(r), len(r)) - no_email_share,
            )
            for a, r in reached.items()
        }
    return out
