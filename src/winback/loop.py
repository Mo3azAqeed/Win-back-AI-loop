"""The AI loop's scorer: Thompson sampling over subjects, bodies, timing and Trialist offers, with a stand-in writer.

Every choice the loop can make (a subject, a body, a timing for one segment, an offer) has a Beta posterior
over how often it is rewarded. To choose, the loop draws once from each posterior and takes the highest
draw, so choices that look better get more traffic while uncertain ones still get tried.
"""

import math
import random
from dataclasses import dataclass, field
from typing import TypeVar

from winback.offers import Offer
from winback.segments import Segment
from winback.settings import SegmentSettings, Settings, Variant


K = TypeVar("K")


@dataclass(frozen=True)
class Timing:
    label: str
    days: float


ONE_HOUR, TWO_DAYS, FIVE_DAYS = Timing("+1 hour", 1 / 24), Timing("+2 days", 2.0), Timing("+5 days", 5.0)
TIMINGS = (ONE_HOUR, TWO_DAYS, FIVE_DAYS)


def read_shift(days_after_trigger: float, behaviour: SegmentSettings) -> float:
    """How the moment an email actually goes out changes reading, on the log-odds scale: the shift of
    the nearest timing, so an email held back by the 48-hour gap is read as when it really arrives.
    +2 days is the reference."""
    nearest = min(TIMINGS, key=lambda t: abs(t.days - days_after_trigger))
    return {ONE_HOUR: behaviour.read_shift_1_hour, TWO_DAYS: 0.0, FIVE_DAYS: behaviour.read_shift_5_days}[nearest]


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


@dataclass
class _Posterior:
    """A Beta posterior, and the real outcomes it has seen. A reward is usually 0 or 1; an offer's is the
    share of the full price a payment brought, so a discounted payment counts as half."""

    a: float = 1.0
    b: float = 1.0
    tries: int = 0
    rewards: float = 0.0

    @property
    def mean(self) -> float:
        return self.a / (self.a + self.b)

    @property
    def variance(self) -> float:
        n = self.a + self.b
        return self.a * self.b / (n * n * (n + 1))

    def learn(self, reward: float) -> None:
        self.a, self.b = self.a + reward, self.b + (1 - reward)
        self.tries, self.rewards = self.tries + 1, self.rewards + reward


@dataclass
class LoopVariant:
    """A subject or body in play: its words, its hidden quality and appeal, and what the loop has seen."""

    text: str
    cta: str
    quality: float
    appeal: float  # the hidden quality as a shift on the log-odds of reading (subject) or clicking (body)
    posterior: _Posterior = field(default_factory=_Posterior)
    retired: bool = False


@dataclass(frozen=True)
class Copy:
    """The words one email goes out with, and their hidden appeal as shifts on the log-odds of reading
    (subject) and clicking (body)."""

    subject: LoopVariant
    body: LoopVariant
    subject_appeal: float
    body_appeal: float


@dataclass(frozen=True)
class VariantRecord:
    text: str
    cta: str
    quality: float
    sends: int
    clicks: int
    retired: bool
    leading: bool


@dataclass(frozen=True)
class TimingRecord:
    label: str
    assigned: int  # merchants assigned it and judged at the horizon (emailed or skipped; never the holdout)
    reached: int
    leading: bool


@dataclass(frozen=True)
class OfferRecord:
    offer: Offer
    assigned: int  # Trialists assigned it and judged at the horizon (emailed or skipped; never the holdout)
    revenue_share: float  # their first-month revenue, in full prices: a discounted payment counts as half
    leading: bool


@dataclass(frozen=True)
class SegmentCopyRecord:
    """The first draft a Drafter or Trialist email goes out with, and how its sends went."""

    subject: str
    body: str
    cta: str
    sends: int
    clicks: int


@dataclass(frozen=True)
class CopyChange:
    """A subject or body the writer added to Idle's tests, or one the loop dropped, and when."""

    day: float
    slot: str  # "subject" or "body"
    change: str  # "written" or "dropped"
    text: str
    cta: str
    sends: int  # so far; 0 when written
    clicks: int
    by: str  # who wrote it: "you" (your first draft) or "stand-in writer"


@dataclass(frozen=True)
class WeekLeaders:
    """The Idle subject and body leading at the end of a week."""

    week: int
    subject: str
    body: str
    cta: str


@dataclass(frozen=True)
class LoopReport:
    """What the AI loop has tried and where it stands: Idle subjects and bodies in the order the writer
    added them (your first draft first), what Drafters and Trialists were sent, and each segment's timings."""

    subjects: list[VariantRecord]
    bodies: list[VariantRecord]
    segment_copy: dict[Segment, SegmentCopyRecord]
    carry_over: float
    timings: dict[Segment, list[TimingRecord]]
    offers: list[OfferRecord]
    history: list[CopyChange]  # in the order it happened
    weekly_leaders: list[WeekLeaders]


class AiLoop:
    """Chooses what each emailed merchant gets and learns from what happens.

    - Idle tests a few subjects and bodies at a time and learns from human clicks, at send time.
      Until every variant in play has enough sends to be judged, they share the traffic evenly;
      otherwise Thompson sampling would starve a poor variant before it could ever be judged, and
      the writer would never get another turn (ADR 0004). Once the leader is clearly better than
      another variant, that variant is retired and the writer adds the next one from its list. The
      newcomer starts from a cautious prior, so a few lucky clicks don't make it the leader at once.
    - Drafters and Trialists get their own first drafts, plus the carry-over share of the edge the
      Idle leader has over your Idle first draft.
    - Every segment learns timing from the goal action of every merchant assigned that timing,
      judged when the horizon closes. Trialist offers learn the same way, from the revenue each
      Trialist brought, so a discounted payment counts as half.

    Each segment draws from its own random stream, so what happens in one segment never changes the
    luck of another's choices."""

    def __init__(self, settings: Settings, rngs: dict[Segment, random.Random]) -> None:
        if not 0 <= settings.loop.carry_over <= 1:
            raise ValueError(f"ai_loop.carry_over must be between 0 and 1, not {settings.loop.carry_over:g}")
        self.rules, self.rngs = settings.loop, rngs
        self.today = 0.0
        self.history: list[CopyChange] = []
        self.weekly_leaders: list[WeekLeaders] = []
        idle, draft = settings.segments[Segment.IDLE], settings.first_drafts[Segment.IDLE.value]
        self.read_rate, self.click_rate = idle.read_rate, idle.click_rate
        self.waiting = {"subject": list(settings.prewritten_subjects), "body": list(settings.prewritten_bodies)}
        self.variants: dict[str, list[LoopVariant]] = {"subject": [], "body": []}
        self._add("subject", Variant(draft.subject, "", 100.0, placeholder=False), _Posterior(), by="you")
        self._add("body", Variant(draft.body, draft.cta, 100.0, placeholder=False), _Posterior(), by="you")
        for slot in self.variants:
            while len(self._active(slot)) < self.rules.active_variants and self.waiting[slot]:
                self._add(slot, self.waiting[slot].pop(0), _Posterior())
        # A Drafter or Trialist first draft is never replaced; its posteriors only count sends and clicks.
        self.own_first_drafts = {
            s: (LoopVariant(d.subject, cta="", quality=100.0, appeal=0.0), LoopVariant(d.body, d.cta, quality=100.0, appeal=0.0))
            for s in (Segment.DRAFTER, Segment.TRIALIST)
            for d in [settings.first_drafts[s.value]]
        }
        self.timings = {s: {t: _Posterior() for t in TIMINGS} for s in Segment}
        self.offers = {o: _Posterior() for o in Offer}

    def choose_timing(self, segment: Segment) -> Timing:
        return self._draw_best(segment, self.timings[segment])

    def choose_offer(self) -> Offer:
        return self._draw_best(Segment.TRIALIST, self.offers)

    def choose_copy(self, segment: Segment) -> Copy:
        """The words for one email: an Idle subject and body drawn from those in play, or the segment's
        own first draft with the carry-over share of the Idle leaders' appeal."""
        if segment is Segment.IDLE:
            subject, body = self._draw_variant("subject"), self._draw_variant("body")
            return Copy(subject, body, subject.appeal, body.appeal)
        carry = self.rules.carry_over
        subject, body = self.own_first_drafts[segment]
        return Copy(subject, body, carry * self._leader("subject").appeal, carry * self._leader("body").appeal)

    def learn_from_click(self, segment: Segment, copy: Copy, clicked: bool, day: float) -> None:
        """An email went out on this day. An Idle subject and body learn whether a human clicked; a
        Drafter or Trialist first draft only counts its sends and clicks. Every click counts as human
        until scanner clicks are simulated (#10)."""
        self.today = day
        for slot, variant in (("subject", copy.subject), ("body", copy.body)):
            variant.posterior.learn(clicked)
            if segment is Segment.IDLE:
                self._review(slot)

    def learn_from_assignment(self, segment: Segment, timing: Timing, reached: bool) -> None:
        self.timings[segment][timing].learn(reached)

    def end_week(self, week: int) -> None:
        """Note which Idle subject and body lead as this week ends."""
        subject, body = self._leader("subject"), self._leader("body")
        self.weekly_leaders.append(WeekLeaders(week, subject.text, body.text, body.cta))

    def learn_from_revenue(self, offer: Offer, revenue_share: float) -> None:
        """A Trialist assigned this offer reached its horizon having brought this share of the full price."""
        self.offers[offer].learn(revenue_share)

    def report(self) -> LoopReport:
        def records(slot: str) -> list[VariantRecord]:
            leader = self._leader(slot)
            return [
                VariantRecord(v.text, v.cta, v.quality, v.posterior.tries, int(v.posterior.rewards), v.retired, v is leader)
                for v in self.variants[slot]
            ]

        timings = {}
        for segment, posteriors in self.timings.items():
            best = max(posteriors, key=lambda t: posteriors[t].mean)
            timings[segment] = [TimingRecord(t.label, p.tries, int(p.rewards), t is best) for t, p in posteriors.items()]
        best_offer = max(self.offers, key=lambda o: self.offers[o].mean)
        offers = [OfferRecord(o, p.tries, p.rewards, o is best_offer) for o, p in self.offers.items()]
        segment_copy = {
            segment: SegmentCopyRecord(subject.text, body.text, body.cta, body.posterior.tries, int(body.posterior.rewards))
            for segment, (subject, body) in self.own_first_drafts.items()
        }
        return LoopReport(records("subject"), records("body"), segment_copy, self.rules.carry_over, timings, offers, list(self.history), list(self.weekly_leaders))

    def _add(self, slot: str, variant: Variant, prior: _Posterior, by: str = "stand-in writer") -> None:
        reference = self.read_rate if slot == "subject" else self.click_rate
        # A certain or impossible chance can't be shifted, so there quality has no effect.
        certain = reference <= 0 or reference >= 1
        appeal = 0.0 if certain else _logit(min(0.999, reference * variant.quality / 100)) - _logit(reference)
        self.variants[slot].append(LoopVariant(variant.text, variant.cta, variant.quality, appeal, prior))
        self.history.append(CopyChange(self.today, slot, "written", variant.text, variant.cta, 0, 0, by))

    def _active(self, slot: str) -> list[LoopVariant]:
        return [v for v in self.variants[slot] if not v.retired]

    def _leader(self, slot: str) -> LoopVariant:
        return max(self._active(slot), key=lambda v: v.posterior.mean)

    def _draw_variant(self, slot: str) -> LoopVariant:
        active = self._active(slot)
        rng = self.rngs[Segment.IDLE]
        if any(v.posterior.tries < self.rules.min_sends for v in active):
            return rng.choice(active)  # an even share, until every variant can be judged
        return active[self._draw_best(Segment.IDLE, {i: v.posterior for i, v in enumerate(active)})]

    def _draw_best(self, segment: Segment, posteriors: "dict[K, _Posterior]") -> K:
        rng = self.rngs[segment]
        draws = {key: rng.betavariate(p.a, p.b) for key, p in posteriors.items()}
        return max(draws, key=lambda key: draws[key])

    def _review(self, slot: str) -> None:
        """Retire a variant once the leader is clearly better, and let the writer replace it."""
        active, leader = self._active(slot), self._leader(slot)
        for variant in active:
            if variant is leader or min(variant.posterior.tries, leader.posterior.tries) < self.rules.min_sends:
                continue
            if _chance_better(leader.posterior, variant.posterior) < self.rules.retire_confidence:
                continue
            variant.retired = True
            sends, clicks = variant.posterior.tries, int(variant.posterior.rewards)
            self.history.append(CopyChange(self.today, slot, "dropped", variant.text, variant.cta, sends, clicks, ""))
            if self.waiting[slot]:
                staying = self._active(slot)
                average = sum(v.posterior.mean for v in staying) / len(staying)
                strength = self.rules.prior_sends
                self._add(slot, self.waiting[slot].pop(0), _Posterior(average * strength, (1 - average) * strength))
            return


def _chance_better(leader: _Posterior, other: _Posterior) -> float:
    """How likely the leader's true rate is above the other's, by the normal approximation to both posteriors."""
    spread = math.sqrt(leader.variance + other.variance)
    return 0.5 * (1 + math.erf((leader.mean - other.mean) / (spread * math.sqrt(2))))
