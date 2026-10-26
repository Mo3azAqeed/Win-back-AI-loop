"""The AI loop: champion against challenger for Idle's email, Thompson sampling for timing and Trialist offers,
and a stand-in writer.

Idle's email comes in versions. Version 0 is your first draft and starts as the champion. The writer brings a
challenger, the champion with one part changed and a hypothesis saying why, and it gets a third of Idle's
emails (challenger_share) until the test ends with a verdict (ADR 0007). Every verdict, won or lost, goes into the playbook.

Timing and offers are not part of a version: every choice there (a timing for one segment, an offer) has a
Beta posterior over how often it is rewarded, and the loop draws once from each and takes the highest draw.
"""

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

from winback.copywriter import Copywriter, StandIn
from winback.segments import Segment
from winback.settings import Email, SegmentSettings, Settings, Variant
from winback.trialist import Offer
from winback.world import DAYS_PER_WEEK, last_entry_day


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
    full_rewards: int = 0  # rewards of exactly 1: clicks, or merchants who reached the goal

    @property
    def mean(self) -> float:
        return self.a / (self.a + self.b)

    @property
    def variance(self) -> float:
        n = self.a + self.b
        return self.a * self.b / (n * n * (n + 1))

    def learn(self, reward: float) -> None:
        self.a, self.b = self.a + reward, self.b + (1 - reward)
        self.tries, self.rewards, self.full_rewards = self.tries + 1, self.rewards + reward, self.full_rewards + (reward == 1)


@dataclass
class LoopVariant:
    """A subject or body: its words, its hidden quality, appeal and follow-through, and every send it went out in."""

    text: str
    cta: str
    quality: float
    appeal: float  # the hidden quality as a shift on the log-odds of reading (subject) or clicking (body)
    follow_through: float = 1.0  # hidden: how likely a merchant who clicks is to act, against your first draft
    posterior: _Posterior = field(default_factory=_Posterior)


@dataclass
class _Version:
    """A whole Idle email: a subject and a body with its button."""

    number: int
    subject: LoopVariant
    body: LoopVariant
    hypothesis: str
    by: str
    changed: str | None  # the part changed from the champion it was tested against; None for your email
    introduced: float
    crowned: float | None = None
    sunset: float | None = None
    sends: int = 0
    clicks: int = 0
    goals_judged: int = 0
    goals: int = 0


@dataclass
class _Arm:
    """One version's results inside one test."""

    version: _Version
    sends: int = 0
    clicks: int = 0
    goals_judged: int = 0  # emails whose miss window has closed
    goals: int = 0

    def clicks_posterior(self) -> _Posterior:
        return _Posterior(1.0 + self.clicks, 1.0 + self.sends - self.clicks)

    def goals_posterior(self) -> _Posterior:
        return _Posterior(1.0 + self.goals, 1.0 + self.goals_judged - self.goals)


@dataclass
class _Test:
    """One champion against one challenger, from the day the challenger entered."""

    number: int
    started: float
    champion: _Arm
    challenger: _Arm


class Ending(Enum):
    """The four ways a test can end."""

    CHALLENGER_WON = "challenger won"
    CHAMPION_WON = "champion won"
    SAME = "the same"
    LIMIT = "too close to call"


@dataclass(frozen=True)
class Copy:
    """The words one email goes out with, their hidden appeal as shifts on the log-odds of reading (subject)
    and clicking (body), and their hidden follow-through. An Idle email names its version and test."""

    subject: LoopVariant
    body: LoopVariant
    subject_appeal: float
    body_appeal: float
    follow_through: float = 1.0
    version: int | None = None
    test: int | None = None


@dataclass(frozen=True)
class VariantRecord:
    text: str
    cta: str
    quality: float
    sends: int
    clicks: int
    sunset: bool  # in neither the champion nor the challenger at the end
    leading: bool  # in the champion at the end


@dataclass(frozen=True)
class VersionRecord:
    """One Idle version, from when it was written to the end of the weeks. Its sends and clicks count every
    email it went out in; goals count those whose miss window has closed and that reached the goal in it."""

    number: int
    subject: str
    body: str
    cta: str
    hypothesis: str
    by: str
    changed: str | None
    quality: tuple[float, float]  # hidden: the subject's and the body's
    introduced_day: float
    crowned_day: float | None  # when it won a test; your email is the champion from the start
    sunset_day: float | None
    status: str  # "champion", "challenger" or "sunset"
    sends: int
    clicks: int
    goals_judged: int
    goals: int


@dataclass(frozen=True)
class PlaybookEntry:
    """One finished test: the two versions, the hypothesis, each one's evidence in the test, how it ended,
    and what was concluded."""

    test: int
    champion: int
    challenger: int
    hypothesis: str
    changed: str
    started: float
    ended: float
    ending: Ending
    champion_sends: int
    champion_clicks: int
    champion_goals_judged: int
    champion_goals: int
    challenger_sends: int
    challenger_clicks: int
    challenger_goals_judged: int
    challenger_goals: int
    chance_better: float  # how likely the challenger's click rate is above the champion's
    chance_same: float  # how likely the two click rates are within the margin of each other
    conclusion: str


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

    def revenue_per_trialist(self, monthly_price: float) -> float | None:
        """Average first-month revenue per Trialist assigned this offer; None before any is judged."""
        return self.revenue_share * monthly_price / self.assigned if self.assigned else None


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
    """A subject or body that entered Idle's tests in a new version, or left them with a sunset version, and when."""

    day: float
    slot: str  # "subject" or "body"
    change: str  # "written" or "dropped"
    text: str
    cta: str
    sends: int  # of the version it left with; 0 when written
    clicks: int
    by: str  # who wrote it: "you" (your first draft) or "stand-in writer"


@dataclass(frozen=True)
class WeekLeaders:
    """Idle's champion at the end of a week, and the challenger being tested against it, if any."""

    week: int
    subject: str
    body: str
    cta: str
    champion: int
    challenger: int | None


@dataclass(frozen=True)
class LoopReport:
    """What the AI loop has tried and where it stands: Idle's versions and the playbook of its tests; the
    subjects and bodies those versions used, in the order they were written (your first draft first); what
    Drafters and Trialists were sent; and each segment's timings and the Trialist offers."""

    versions: list[VersionRecord]
    playbook: list[PlaybookEntry]
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

    - Idle runs one test at a time: the champion against a challenger, which gets a third of Idle's emails. A test
      ends at the end of a week once the loop is sure enough (ADR 0007): the challenger won on clicks
      without clearly fewer goal actions, the champion won, the two are the same, or the test hit its limit
      (too close to call: the version ahead on clicks stays, kept but not proven). Then the writer brings the next
      challenger, so no test ever waits.
    - Drafters and Trialists get their own first drafts, plus the carry-over share of the edge the
      Idle champion has over your Idle first draft.
    - Every segment learns timing from the goal action of every merchant assigned that timing,
      judged when the horizon closes. Trialist offers learn the same way, from the revenue each
      Trialist brought, so a discounted payment counts as half.

    Each segment draws from its own random stream, so what happens in one segment never changes the
    luck of another's choices."""

    def __init__(self, settings: Settings, rngs: dict[Segment, random.Random], copywriter: Copywriter | None = None) -> None:
        if not 0 <= settings.loop.carry_over <= 1:
            raise ValueError(f"ai_loop.carry_over must be between 0 and 1, not {settings.loop.carry_over:g}")
        self.rules, self.rngs = settings.loop, rngs
        self.today = 0.0
        self.history: list[CopyChange] = []
        self.weekly_leaders: list[WeekLeaders] = []
        self.playbook: list[PlaybookEntry] = []
        idle, draft = settings.segments[Segment.IDLE], settings.first_drafts[Segment.IDLE.value]
        self.read_rate, self.click_rate = idle.read_rate, idle.click_rate
        self.copywriter: Copywriter = copywriter or StandIn(settings)
        self.asked = {"subject": 0, "body": 0}  # challenger parts asked of the copywriter so far, per part
        self.next_change = "subject"
        self.last_signup_day = last_entry_day(settings)  # no new Idle merchant arrives after it, so no test starts
        subject = self._part("subject", Variant(draft.subject, "", 100.0, placeholder=False), by="you")
        body = self._part("body", Variant(draft.body, draft.cta, 100.0, placeholder=False), by="you")
        self.versions = [_Version(0, subject, body, "Your email.", "you", None, 0.0)]
        self.champion = self.versions[0]
        self.test: _Test | None = None
        self._next_challenger()
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
        """The words for one email: in Idle the champion or, for its share while a test runs, the challenger; else
        the segment's own first draft with the carry-over share of the Idle champion's appeal."""
        if segment is Segment.IDLE:
            version = self.champion
            if self.test is not None and self.rngs[Segment.IDLE].random() < self.rules.challenger_share:
                version = self.test.challenger.version
            subject, body = version.subject, version.body
            test = self.test.number if self.test is not None else None
            return Copy(subject, body, subject.appeal, body.appeal, subject.follow_through * body.follow_through, version.number, test)
        carry = self.rules.carry_over
        subject, body = self.own_first_drafts[segment]
        return Copy(subject, body, carry * self.champion.subject.appeal, carry * self.champion.body.appeal)

    def learn_from_click(self, segment: Segment, copy: Copy, clicked: bool, day: float) -> None:
        """An email went out on this day, and a human clicked it or not. Every click counts as human until
        scanner clicks are simulated (#10)."""
        self.today = day
        for variant in (copy.subject, copy.body):
            variant.posterior.learn(clicked)
        if copy.version is None:
            return
        version = self.versions[copy.version]
        version.sends, version.clicks = version.sends + 1, version.clicks + clicked
        arm = self._arm(copy)
        if arm is not None:
            arm.sends, arm.clicks = arm.sends + 1, arm.clicks + clicked
        # The limit holds between week ends too, so a test started mid-week never runs past it.
        test = self.test
        if test is not None and (max(test.champion.sends, test.challenger.sends) >= self.rules.test_max_sends or day - test.started >= self.rules.test_max_weeks * DAYS_PER_WEEK):
            self._end_test(test, Ending.LIMIT)

    def learn_from_goal(self, copy: Copy, reached: bool) -> None:
        """An Idle email's miss window closed: the merchant reached the goal in it or not."""
        if copy.version is None:
            return
        version = self.versions[copy.version]
        version.goals_judged, version.goals = version.goals_judged + 1, version.goals + reached
        arm = self._arm(copy)
        if arm is not None:
            arm.goals_judged, arm.goals = arm.goals_judged + 1, arm.goals + reached

    def learn_from_assignment(self, segment: Segment, timing: Timing, reached: bool) -> None:
        self.timings[segment][timing].learn(reached)

    def end_week(self, week: int) -> None:
        """At the end of each week, the test running in Idle may reach its verdict; then note the champion and the challenger."""
        self.today = week * DAYS_PER_WEEK
        if self.test is not None:
            ending = self._verdict(self.test)
            if ending is not None:
                self._end_test(self.test, ending)
        challenger = self.test.challenger.version.number if self.test is not None else None
        c = self.champion
        self.weekly_leaders.append(WeekLeaders(week, c.subject.text, c.body.text, c.body.cta, c.number, challenger))

    def learn_from_revenue(self, offer: Offer, revenue_share: float) -> None:
        """A Trialist assigned this offer reached its horizon having brought this share of the full price."""
        self.offers[offer].learn(revenue_share)

    def report(self) -> LoopReport:
        in_play = [self.champion] + ([self.test.challenger.version] if self.test is not None else [])

        def records(slot: str) -> list[VariantRecord]:
            parts: list[LoopVariant] = []
            for version in self.versions:
                part = version.subject if slot == "subject" else version.body
                if all(part is not p for p in parts):
                    parts.append(part)
            current = [v.subject if slot == "subject" else v.body for v in in_play]
            champion_part = self.champion.subject if slot == "subject" else self.champion.body
            return [
                VariantRecord(p.text, p.cta, p.quality, p.posterior.tries, p.posterior.full_rewards, all(p is not c for c in current), p is champion_part)
                for p in parts
            ]

        timings = {}
        for segment, posteriors in self.timings.items():
            best = max(posteriors, key=lambda t: posteriors[t].mean)
            timings[segment] = [TimingRecord(t.label, p.tries, p.full_rewards, t is best) for t, p in posteriors.items()]
        best_offer = max(self.offers, key=lambda o: self.offers[o].mean)
        offers = [OfferRecord(o, p.tries, p.rewards, o is best_offer) for o, p in self.offers.items()]
        segment_copy = {
            segment: SegmentCopyRecord(subject.text, body.text, body.cta, body.posterior.tries, body.posterior.full_rewards)
            for segment, (subject, body) in self.own_first_drafts.items()
        }
        versions = [self._record(v) for v in self.versions]
        return LoopReport(
            versions, list(self.playbook), records("subject"), records("body"), segment_copy, self.rules.carry_over, timings, offers,
            list(self.history), list(self.weekly_leaders),
        )

    def _record(self, v: _Version) -> VersionRecord:
        status = "champion" if v is self.champion else "challenger" if self.test is not None and v is self.test.challenger.version else "sunset"
        return VersionRecord(
            v.number, v.subject.text, v.body.text, v.body.cta, v.hypothesis, v.by, v.changed, (v.subject.quality, v.body.quality),
            v.introduced, v.crowned, v.sunset, status, v.sends, v.clicks, v.goals_judged, v.goals,
        )

    def _part(self, slot: str, variant: Variant, by: str) -> LoopVariant:
        reference = self.read_rate if slot == "subject" else self.click_rate
        # A certain or impossible chance can't be shifted, so there quality has no effect.
        certain = reference <= 0 or reference >= 1
        appeal = 0.0 if certain else _logit(min(0.999, reference * variant.quality / 100)) - _logit(reference)
        self.history.append(CopyChange(self.today, slot, "written", variant.text, variant.cta, 0, 0, by))
        return LoopVariant(variant.text, variant.cta, variant.quality, appeal, variant.follow_through / 100)

    def _next_challenger(self) -> None:
        """The writer's next challenger: the champion with one part changed, subjects and bodies in turn."""
        self.test = None  # until a challenger arrives, the champion is sent alone
        if self.today >= self.last_signup_day:
            return  # no merchants are left to test on
        c = self.champion
        champion = Email(c.subject.text, c.body.text, c.body.cta)
        conclusions = [e.conclusion for e in self.playbook]
        # The preferred part first, then the other: a writer with nothing more for one part, or whose every draft
        # failed a check, still gets to change the other.
        for slot in (self.next_change, "body" if self.next_change == "subject" else "subject"):
            nth, self.asked[slot] = self.asked[slot], self.asked[slot] + 1
            variant = self.copywriter.challenger(slot, champion, conclusions, nth)
            if variant is not None:
                break
        else:
            return  # nothing from the writer this time: the champion is sent alone
        self.next_change = "body" if slot == "subject" else "subject"
        part = self._part(slot, variant, by=self.copywriter.name)
        version = _Version(
            len(self.versions), part if slot == "subject" else c.subject, part if slot == "body" else c.body,
            variant.hypothesis, self.copywriter.name, slot, self.today,
        )
        self.versions.append(version)
        number = len(self.playbook) + 1
        self.test = _Test(number, self.today, _Arm(c), _Arm(version))

    def _arm(self, copy: Copy) -> _Arm | None:
        """The arm of the running test this email was sent for, if that test is still running."""
        if self.test is None or copy.test != self.test.number:
            return None
        return self.test.champion if copy.version == self.test.champion.version.number else self.test.challenger

    def _verdict(self, test: _Test) -> Ending | None:
        """How the test ends this week, if it does."""
        champion, challenger, sure = test.champion, test.challenger, self.rules.verdict_confidence
        if min(champion.sends, challenger.sends) >= self.rules.min_sends:
            better = _chance_better(challenger.clicks_posterior(), champion.clicks_posterior())
            if better >= sure:
                return Ending.CHALLENGER_WON
            if better <= 1 - sure:
                return Ending.CHAMPION_WON
            if _chance_within(challenger.clicks_posterior(), champion.clicks_posterior(), self.rules.same_margin) >= sure:
                return Ending.SAME
        if self.today - test.started >= self.rules.test_max_weeks * DAYS_PER_WEEK - 1e-9:
            return Ending.LIMIT
        return None

    def _end_test(self, test: _Test, ending: Ending) -> None:
        champion, challenger = test.champion, test.challenger
        better = _chance_better(challenger.clicks_posterior(), champion.clicks_posterior())
        same = _chance_within(challenger.clicks_posterior(), champion.clicks_posterior(), self.rules.same_margin)
        fewer_goals = _chance_better(champion.goals_posterior(), challenger.goals_posterior()) >= self.rules.verdict_confidence
        clickbait = ending is Ending.CHALLENGER_WON and fewer_goals
        if clickbait:
            ending = Ending.CHAMPION_WON
        # Too close to call: the version ahead on clicks stays, if the settings say so; it is kept, not proven better.
        kept_ahead = ending is Ending.LIMIT and self.rules.keep_ahead_at_limit and better > 0.5 and not fewer_goals
        held_back_by_goals = ending is Ending.LIMIT and better > 0.5 and fewer_goals  # ahead on clicks, behind on goals
        winner = challenger if ending is Ending.CHALLENGER_WON or kept_ahead else champion
        loser = champion if winner is challenger else challenger
        loser.version.sunset = self.today
        if winner is challenger:
            challenger.version.crowned = self.today
            self.champion = challenger.version
        slot = challenger.version.changed or "subject"
        gone = loser.version.subject if slot == "subject" else loser.version.body
        self.history.append(CopyChange(self.today, slot, "dropped", gone.text, gone.cta, loser.version.sends, loser.version.clicks, ""))
        self.playbook.append(
            PlaybookEntry(
                test.number, champion.version.number, challenger.version.number, challenger.version.hypothesis, slot, test.started, self.today, ending,
                champion.sends, champion.clicks, champion.goals_judged, champion.goals,
                challenger.sends, challenger.clicks, challenger.goals_judged, challenger.goals,
                better, same, _conclusion(test, ending, better, same, clickbait or held_back_by_goals, kept_ahead),
            )
        )
        self._next_challenger()

    def _draw_best(self, segment: Segment, posteriors: "dict[K, _Posterior]") -> K:
        rng = self.rngs[segment]
        draws = {key: rng.betavariate(p.a, p.b) for key, p in posteriors.items()}
        return max(draws, key=lambda key: draws[key])


def _rate(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _conclusion(test: _Test, ending: Ending, better: float, same: float, clickbait: bool, kept_ahead: bool) -> str:
    """One line a reader can act on: the change, how it did on clicks, how sure the loop is, and what happened."""
    champion, challenger = test.champion, test.challenger
    points = (_rate(challenger.clicks, challenger.sends) - _rate(champion.clicks, champion.sends)) * 100
    change = f"v{challenger.version.number} (new {challenger.version.changed}) against v{champion.version.number}: {points:+.1f} click points, {better:.0%} sure it is better"
    if clickbait:
        goal_points = (_rate(challenger.goals, challenger.goals_judged) - _rate(champion.goals, champion.goals_judged)) * 100
        return f"{change}, but {goal_points:+.1f} goal points: more clicks, fewer goal actions, so it lost and is sunset."
    if kept_ahead:
        return f"{change}; too close to call at the test's limit, but ahead, so it takes over as champion (kept, not proven) and v{champion.version.number} is sunset."
    return change + {
        Ending.CHALLENGER_WON: f"; crowned, and v{champion.version.number} is sunset.",
        Ending.CHAMPION_WON: f"; it lost and is sunset, v{champion.version.number} stays.",
        Ending.SAME: f"; {same:.0%} sure they are the same within the margin, so v{champion.version.number} stays and v{challenger.version.number} is sunset.",
        Ending.LIMIT: f"; too close to call at the test's limit, so v{champion.version.number} stays and v{challenger.version.number} is sunset.",
    }[ending]


def _chance_better(leader: _Posterior, other: _Posterior) -> float:
    """How likely the leader's true rate is above the other's, by the normal approximation to both posteriors."""
    spread = math.sqrt(leader.variance + other.variance)
    return 0.5 * (1 + math.erf((leader.mean - other.mean) / (spread * math.sqrt(2))))


def _chance_within(one: _Posterior, other: _Posterior, margin: float) -> float:
    """How likely the two true rates are within the margin of each other, by the same normal approximation."""
    spread, gap = math.sqrt(one.variance + other.variance), one.mean - other.mean

    def below(x: float) -> float:
        return 0.5 * (1 + math.erf((x - gap) / (spread * math.sqrt(2))))

    return below(margin) - below(-margin)
