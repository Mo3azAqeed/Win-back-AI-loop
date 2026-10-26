"""What each approach achieved, counted from the calendar runs: per segment, true lift on the same merchants,
week by week as results became known, the emails and how they scored, and the AI loop's Trialist offers.

True lift always compares the same merchants: the ones who would be in the segment with no email, the
holdout aside. `judged_merchants` is that rule, and everything here counts through it.
"""

import math
from dataclasses import dataclass

from winback.lifecycle import Approach, CalendarRun, EmailFate, EmailResult, Stay, StayResult
from winback.segments import Segment
from winback.settings import Settings
from winback.trialist import Offer
from winback.world import DAYS_PER_WEEK


def judged_merchants(no_email: list[StayResult], segment: Segment) -> set[str]:
    """The merchants true lift is measured on: those in the segment with no email, the holdout aside. An email
    can push more merchants into a later segment; they are that earlier email's win, already counted there."""
    return {r.merchant_key for r in no_email if r.segment is segment and not r.holdout}


def _rate(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


@dataclass(frozen=True)
class EmailTally:
    sent: int
    skipped: int
    hits: int  # followed by the goal action inside the miss window
    misses: int

    def __add__(self, other: "EmailTally") -> "EmailTally":
        return EmailTally(self.sent + other.sent, self.skipped + other.skipped, self.hits + other.hits, self.misses + other.misses)


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


def _outcome(run: CalendarRun, segment: Segment, merchants: set[str], paid_window_days: float, no_email_share: float) -> SegmentOutcome:
    """One segment's counted stays for these merchants. Holdout merchants only ever have ghost sends,
    so they have no scored emails."""
    results = [r for r in run.results if r.segment is segment and r.merchant_key in merchants]
    reached = sum(r.reached for r in results)
    stays = [(j, s) for j in run.journeys if j.merchant.key in merchants for s in j.stays if s.segment is segment and s.counted]
    scored = [e for e in run.email_results if e.segment is segment and e.merchant_key in merchants]
    emails = _emails([s for _, s in stays], scored)
    paid = sum(j.paid_at is not None and s.entered <= j.paid_at <= s.entered + paid_window_days for j, s in stays)
    lift = _rate(reached, len(results)) - no_email_share
    return SegmentOutcome(len(results), reached, emails, lift, paid, sum(r.first_month_revenue for r in results))


@dataclass(frozen=True)
class Outcomes:
    """Every approach's results per segment, split by which merchants they count."""

    judged: dict[Segment, dict[Approach, SegmentOutcome]]  # emailed merchants who would be in the segment with no email
    pushed: dict[Segment, dict[Approach, SegmentOutcome]]  # emailed merchants an earlier email pushed into it
    baselines: dict[Segment, SegmentOutcome]  # the holdout, never emailed


def segment_outcomes(runs: dict[Approach, CalendarRun], paid_window_days: float) -> Outcomes:
    """Per segment and approach: how many reached the goal action within the horizon, true lift against
    no email, the emails and how they scored, paid conversion within the paid window, and first-month
    revenue.

    Merchants an earlier email pushed into a segment are reported apart, with no lift. Nothing comes
    before Idle, so no email pushes anyone into it. The holdout is never emailed; its goal rate is each
    segment's baseline, taken from an emailing approach (a holdout merchant behaves the same in every one)."""
    held = {j.merchant.key for j in runs[Approach.NO_EMAIL].journeys if j.merchant.holdout}
    emailing = runs[Approach.HAND_WRITTEN]
    judged: dict[Segment, dict[Approach, SegmentOutcome]] = {}
    pushed: dict[Segment, dict[Approach, SegmentOutcome]] = {}
    for segment in Segment:
        would_be_here = judged_merchants(runs[Approach.NO_EMAIL].results, segment)
        no_email = _outcome(runs[Approach.NO_EMAIL], segment, would_be_here, paid_window_days, no_email_share=0.0)
        judged[segment] = {a: _outcome(run, segment, would_be_here, paid_window_days, no_email.reached_share) for a, run in runs.items()}
        pushed[segment] = {}
        for a, run in runs.items():
            pushed_here = judged_merchants(run.results, segment) - would_be_here
            pushed[segment][a] = _outcome(run, segment, pushed_here, paid_window_days, no_email_share=0.0)
    baselines = {segment: _outcome(emailing, segment, held, paid_window_days, no_email_share=0.0) for segment in Segment}
    return Outcomes(judged, pushed, baselines)


def weekly_lift(results: dict[Approach, list[StayResult]], settings: Settings) -> dict[Segment, dict[Approach, list[float]]]:
    """True lift so far, at the end of each week, counts the same merchants true lift does whose result was
    known by then: their horizon, counted from when they would have entered with no email, had closed. That is
    all the AI loop could have learned from by then. The weeks run until the last signup's horizon closes,
    where it is the segment's true lift."""
    longest = max(b.horizon_days for b in settings.segments.values())
    weeks = math.ceil((settings.weeks * DAYS_PER_WEEK + longest) / DAYS_PER_WEEK)
    weekly: dict[Segment, dict[Approach, list[float]]] = {}
    for segment in Segment:
        judged = judged_merchants(results[Approach.NO_EMAIL], segment)
        known_on = {r.merchant_key: r.known_on for r in results[Approach.NO_EMAIL] if r.segment is segment and r.merchant_key in judged}
        reached = {a: {r.merchant_key: r.reached for r in rs if r.segment is segment and r.merchant_key in known_on} for a, rs in results.items()}
        weekly[segment] = {a: [] for a in Approach}
        for week in range(1, weeks + 1):
            known = [key for key, day in known_on.items() if day <= week * DAYS_PER_WEEK]
            share = {a: sum(reached[a][key] for key in known) / len(known) if known else 0.0 for a in Approach}
            for a in Approach:
                weekly[segment][a].append(share[a] - share[Approach.NO_EMAIL])
    return weekly


@dataclass(frozen=True)
class OfferSummary:
    """What the AI loop's Trialist offers did: emails sent with each, Trialists who paid with the
    discount, and how many of them would have paid the full price with no email."""

    sent: dict[Offer, int]
    discounted_payers: int
    would_have_paid_anyway: int


def offer_summary(runs: dict[Approach, CalendarRun]) -> OfferSummary:
    """Counted Trialist stays only (only they have results), whether the merchant would be a Trialist with
    no email or an earlier email pushed it there. A merchant would have paid anyway if, with no email at all,
    it paid at some point in the run: the simulation knows by looking at the same merchant in the no-email run."""
    stays = [s for j in runs[Approach.AI_LOOP].journeys for s in j.stays if s.segment is Segment.TRIALIST and s.counted]
    sent = {o: sum(s.offer is o and s.email is EmailFate.SENT for s in stays) for o in Offer}
    discounted = {r.merchant_key for r in runs[Approach.AI_LOOP].results if r.segment is Segment.TRIALIST and r.reached and r.discounted}
    paid_alone = {j.merchant.key for j in runs[Approach.NO_EMAIL].journeys if j.paid_at is not None}
    return OfferSummary(sent, len(discounted), len(discounted & paid_alone))
