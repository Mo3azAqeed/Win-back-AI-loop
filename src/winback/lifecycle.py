"""Merchants moving through Idle → Drafter → Trialist → paid, with or without the hand-written emails.

Every approach runs on one shared calendar: all merchants' events (entering a segment, an email
falling due, a goal action) are processed strictly in date order, so anything that learns from
outcomes can only ever see what has already happened.
"""

import heapq
import itertools
import math
import random
from dataclasses import dataclass, field
from enum import Enum

from winback.draws import draw
from winback.loop import AiLoop, LoopReport, Timing, read_shift
from winback.segments import NEXT_SEGMENT, Segment
from winback.settings import Settings
from winback.world import Merchant, last_entry_day


class Approach(Enum):
    NO_EMAIL = "no_email"
    HAND_WRITTEN = "hand_written"
    AI_LOOP = "ai_loop"


class EmailFate(Enum):
    NOT_PLANNED = "not planned"
    SENT = "sent"
    SKIPPED = "skipped"  # the merchant moved on, or the trial ended, before the email was due
    # A holdout merchant's send time, picked and skipped exactly like a real email's, with nothing sent.
    GHOST_SENT = "ghost sent"
    GHOST_SKIPPED = "ghost skipped"


@dataclass(frozen=True)
class EmailCopy:
    """An email's hidden appeal, as a shift on the log-odds of reading (subject) and clicking (body).
    Your first draft is the reference: 0, shown as hidden quality 100."""

    subject_appeal: float = 0.0
    body_appeal: float = 0.0


FIRST_DRAFT = EmailCopy()


@dataclass(frozen=True)
class Stay:
    """One merchant's time in one segment. `left` is when it took the goal action (None if not by the end).
    Only stays entered during the weeks of signups are counted; later ones exist only so that counted
    stays can finish their paid window."""

    segment: Segment
    entered: float
    left: float | None
    email: EmailFate
    email_sent_at: float | None
    counted: bool


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
    # On the same day, an email falling due is handled before a goal action, then a horizon or miss window closing.
    EMAIL_DUE = 0
    GOAL = 1
    ENTER = 2
    HORIZON_CLOSES = 3
    MISS_WINDOW_CLOSES = 4


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
    holdout: bool
    first_month_revenue: float  # what the goal action brought, if it was a payment; 0 otherwise


@dataclass(frozen=True)
class EmailResult:
    """Whether an email was followed by the goal action inside its miss window, known on the day the
    window closes (and never before). Until then the email is pending, not a miss."""

    merchant_key: str
    segment: Segment
    entered: float
    sent_on: float
    known_on: float
    goal_day: float | None
    hit: bool


@dataclass
class _OpenStay:
    """One merchant's stay in one segment while the run is going."""

    segment: Segment
    entered: float
    deadline: float
    draws: _Draws
    counted: bool
    timing: Timing | None = None  # the AI loop's choice for this stay
    left: float | None = None
    goal_day: float | None = None
    first_month_revenue: float = 0.0
    email: EmailFate = EmailFate.NOT_PLANNED
    email_sent_at: float | None = None

    def freeze(self) -> Stay:
        return Stay(self.segment, self.entered, self.left, self.email, self.email_sent_at, self.counted)


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
    email_results: list[EmailResult]  # in the order they became known
    event_days: list[float]  # the day of every event, in the order handled
    loop: LoopReport | None  # where the AI loop stands at the end (AI loop only)


class _Calendar:
    """One approach's run: every merchant's events on one timeline, handled in date order.

    Stays entered during the weeks of signups are counted. The run keeps going until every counted
    stay's horizon and paid window have closed; until then merchants keep moving through the
    lifecycle, so a late signup can still pay inside its window."""

    def __init__(self, settings: Settings, merchants: list[Merchant], seed: int, approach: Approach) -> None:
        self.settings, self.seed, self.approach = settings, seed, approach
        self.last_entry_day = last_entry_day(settings)
        self.run_end = self.last_entry_day
        self.merchants = [_MerchantState(i, m) for i, m in enumerate(merchants)]
        self.queue: list[_Scheduled] = []
        self.sequence = itertools.count()
        self.results: list[StayResult] = []
        self.email_results: list[EmailResult] = []
        self.loop = AiLoop(settings, random.Random(int(draw(seed, "ai loop") * 2**53))) if approach is Approach.AI_LOOP else None
        self.event_days: list[float] = []
        for state in self.merchants:
            self._schedule(state, state.merchant.arrival_day, _Event.ENTER)

    def _schedule(self, state: _MerchantState, day: float, event: _Event, stay: _OpenStay | None = None) -> None:
        heapq.heappush(self.queue, _Scheduled(day, event.value, next(self.sequence), event, state.index, stay))

    def run(self) -> CalendarRun:
        while self.queue and self.queue[0].day <= self.run_end:
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
            elif item.event is _Event.MISS_WINDOW_CLOSES and item.stay is not None:
                self._close_miss_window(state, item.stay, item.day)
        journeys = [Journey(s.merchant, tuple(stay.freeze() for stay in s.stays), s.paid_at) for s in self.merchants]
        return CalendarRun(journeys, self.results, self.email_results, self.event_days, self.loop.report() if self.loop else None)

    def _enter(self, state: _MerchantState, segment: Segment, day: float) -> None:
        behaviour = self.settings.segments[segment]
        deadline = day + self.settings.trial_days if segment is Segment.TRIALIST else math.inf
        stay = _OpenStay(segment, day, deadline, _Draws(self.seed, state.merchant, segment), counted=day <= self.last_entry_day)
        state.stays.append(stay)
        if stay.counted:
            closes = day + behaviour.horizon_days
            self.run_end = max(self.run_end, closes, day + self.settings.paid_window_days)
            self._schedule(state, closes, _Event.HORIZON_CLOSES, stay)
        if stay.draws.chance("organic") < behaviour.organic_share:
            organic = day + stay.draws.wait_days("organic_time", behaviour.organic_mean_days)
            if organic <= deadline:
                self._set_goal(state, stay, organic)
        if self.approach is Approach.HAND_WRITTEN:
            self._schedule_email(state, stay, day + behaviour.hand_written_after_days)
        elif self.loop is not None:
            # Holdout merchants get a timing too, picked the same way, for their ghost send.
            stay.timing = self.loop.choose_timing(segment)
            self._schedule_email(state, stay, day + stay.timing.days)

    def _schedule_email(self, state: _MerchantState, stay: _OpenStay, wanted: float) -> None:
        self._schedule(state, max(wanted, state.last_email + self.settings.min_gap_days), _Event.EMAIL_DUE, stay)

    def _email_due(self, state: _MerchantState, stay: _OpenStay, day: float) -> None:
        """The one send path: on its due day an email is sent, or skipped if the merchant moved on
        or the trial ended. A holdout merchant gets a ghost send instead: the same day and the same
        rules, but nothing is sent, so nothing can be read or clicked."""
        ghost = state.merchant.holdout
        if stay.left is not None or day > stay.deadline:
            stay.email = EmailFate.GHOST_SKIPPED if ghost else EmailFate.SKIPPED
            return
        if ghost:
            stay.email, stay.email_sent_at, state.last_email = EmailFate.GHOST_SENT, day, day
            return
        behaviour = self.settings.segments[stay.segment]
        stay.email, stay.email_sent_at, state.last_email = EmailFate.SENT, day, day
        if stay.counted:
            # Idle and Drafter emails are judged from the email; every Trialist from publishing, whatever its offer.
            opens = stay.entered if stay.segment is Segment.TRIALIST else day
            closes = opens + behaviour.miss_window_days
            self.run_end = max(self.run_end, closes)
            self._schedule(state, closes, _Event.MISS_WINDOW_CLOSES, stay)
        subject_appeal, body_appeal, timing_shift = FIRST_DRAFT.subject_appeal, FIRST_DRAFT.body_appeal, 0.0
        chosen = None
        if self.loop is not None:
            chosen = subject, body = self.loop.choose_copy(stay.segment)
            subject_appeal, body_appeal, timing_shift = subject.appeal, body.appeal, read_shift(day - stay.entered, behaviour)
        read = stay.draws.chance("read") < _shifted(behaviour.read_rate, subject_appeal + timing_shift)
        clicked = read and stay.draws.chance("click") < _shifted(behaviour.click_rate, body_appeal)
        if self.loop is not None and chosen is not None:
            self.loop.learn_from_click(stay.segment, *chosen, clicked)
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
            state.paid_at, stay.first_month_revenue = day, self.settings.monthly_price
        else:
            self._enter(state, following, day)

    def _close_horizon(self, state: _MerchantState, stay: _OpenStay, day: float) -> None:
        reached = stay.left is not None  # events run in date order, so any goal so far is inside the horizon
        if self.loop is not None and stay.timing is not None and not state.merchant.holdout:
            self.loop.learn_from_assignment(stay.segment, stay.timing, reached)
        self.results.append(
            StayResult(state.merchant.key, stay.segment, stay.entered, day, stay.left, reached, state.merchant.holdout, stay.first_month_revenue)
        )

    def _close_miss_window(self, state: _MerchantState, stay: _OpenStay, day: float) -> None:
        assert stay.email_sent_at is not None
        hit = stay.left is not None  # events run in date order, and the email only went out while the merchant stayed
        self.email_results.append(EmailResult(state.merchant.key, stay.segment, stay.entered, stay.email_sent_at, day, stay.left, hit))


def run_calendar(settings: Settings, merchants: list[Merchant], seed: int, approach: Approach) -> CalendarRun:
    """Run one approach for every merchant on one shared calendar."""
    return _Calendar(settings, merchants, seed, approach).run()


def _rate(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


@dataclass(frozen=True)
class EmailTally:
    sent: int
    skipped: int
    hits: int  # followed by the goal action inside the miss window
    misses: int


def _emails(stays: list[Stay], results: list[EmailResult]) -> EmailTally:
    """Emails sent and skipped across these stays, and the scored ones that hit or missed. Holdout
    stays only ever have ghost sends, so their tally counts ghost sends and ghost skips."""
    hits = sum(r.hit for r in results)
    sent = sum(s.email in (EmailFate.SENT, EmailFate.GHOST_SENT) for s in stays)
    skipped = sum(s.email in (EmailFate.SKIPPED, EmailFate.GHOST_SKIPPED) for s in stays)
    return EmailTally(sent, skipped, hits, len(results) - hits)


@dataclass(frozen=True)
class SegmentOutcome:
    counted: int
    reached: int
    emails: EmailTally
    true_lift: float
    paid_in_window: int  # merchants who paid within the paid window of entering this segment
    first_month_revenue: float  # from payments within the horizon (Trialists paying)

    @property
    def reached_share(self) -> float:
        return _rate(self.reached, self.counted)

    @property
    def paid_share(self) -> float:
        return _rate(self.paid_in_window, self.counted)


def _outcome(run: CalendarRun, segment: Segment, held_out: bool, paid_window_days: float, no_email_share: float) -> SegmentOutcome:
    """One segment's counted stays, either of emailed merchants or of the holdout. The holdout's
    emails are ghost sends, so it never has scored emails."""
    results = [r for r in run.results if r.segment is segment and r.holdout is held_out]
    reached = sum(r.reached for r in results)
    stays = [(j, s) for j in run.journeys if j.merchant.holdout is held_out for s in j.stays if s.segment is segment and s.counted]
    scored = [] if held_out else [e for e in run.email_results if e.segment is segment]
    emails = _emails([s for _, s in stays], scored)
    paid = sum(j.paid_at is not None and s.entered <= j.paid_at <= s.entered + paid_window_days for j, s in stays)
    lift = _rate(reached, len(results)) - no_email_share
    return SegmentOutcome(len(results), reached, emails, lift, paid, sum(r.first_month_revenue for r in results))


def segment_outcomes(runs: dict[Approach, CalendarRun], paid_window_days: float) -> dict[Segment, dict[Approach, SegmentOutcome]]:
    """Per segment and approach, over the counted stays of emailed merchants: how many reached the goal
    action within the horizon, true lift against no email, the emails and how they scored, paid
    conversion within the paid window, and first-month revenue. The holdout is left out of every
    approach, so true lift is measured on emailed merchants only."""
    out: dict[Segment, dict[Approach, SegmentOutcome]] = {}
    for segment in Segment:
        no_email = _outcome(runs[Approach.NO_EMAIL], segment, held_out=False, paid_window_days=paid_window_days, no_email_share=0.0)
        out[segment] = {
            a: _outcome(run, segment, held_out=False, paid_window_days=paid_window_days, no_email_share=no_email.reached_share)
            for a, run in runs.items()
        }
    return out


def holdout_baselines(run: CalendarRun, paid_window_days: float) -> dict[Segment, SegmentOutcome]:
    """Per segment, the holdout of an emailing approach: its goal rate is the baseline real data would
    measure, and its emails are ghost sends."""
    return {segment: _outcome(run, segment, held_out=True, paid_window_days=paid_window_days, no_email_share=0.0) for segment in Segment}
