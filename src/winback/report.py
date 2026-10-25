"""The report a non-technical reader can follow."""

from typing import TYPE_CHECKING, NamedTuple

from winback.lifecycle import Approach, SegmentOutcome
from winback.loop import LoopReport, VariantRecord
from winback.settings import Settings
from winback.segments import Segment

if TYPE_CHECKING:
    from winback.run import StartResult

class SegmentText(NamedTuple):
    """How a segment is named in the report, what starts its clock, and its goal action (to do, and done)."""

    label: str
    trigger: str
    goal: str
    done: str


SEGMENT_TEXT = {
    Segment.IDLE: SegmentText("Idle", "entering Idle (signup, for new merchants)", "start a draft", "started a draft"),
    Segment.DRAFTER: SegmentText("Drafter", "saving the draft", "publish", "published"),
    Segment.TRIALIST: SegmentText("Trialist", "publishing", "pay", "paid"),
}
APPROACH_LABEL = {Approach.NO_EMAIL: "No email", Approach.HAND_WRITTEN: "Hand-written email (your first draft)", Approach.AI_LOOP: "AI loop"}
HOLDOUT_LABEL = "Holdout (never emailed)"
# Where each segment's miss window starts.
MISS_WINDOW_FROM = {Segment.IDLE: "the email", Segment.DRAFTER: "the email", Segment.TRIALIST: "publishing"}


def render(settings: Settings, seed: int, by_start: "dict[int, StartResult]") -> str:
    lines = [
        "# Win-back simulation report",
        "",
        f"Seed: {seed}. Every number marked as a placeholder below is made up.",
        "",
        "## Your first drafts",
        "",
        "Hidden quality 100: the reference every later email is measured against. {braces} are filled in for each merchant.",
        "",
    ]
    for segment, text in SEGMENT_TEXT.items():
        draft = settings.first_drafts[segment.value]
        lines += [
            f"### {text.label}",
            "",
            f"Sent {settings.segments[segment].hand_written_after_days:g} days after {text.trigger}.",
            "",
            f"> **Subject:** {draft.subject}",
            ">",
            f"> {draft.body}",
            ">",
            f"> **[{draft.cta}]**",
            "",
        ]
    for start, result in by_start.items():
        lines += [
            f"## Starting from {start:,} merchants",
            "",
            f"Merchants today: {result.existing_merchants:,}",
            f"Already paying (not simulated): {result.already_paying:,}",
            "",
            "| Week | New signups |",
            "|---|---|",
            *(f"| {week} | {count:,} |" for week, count in enumerate(result.weekly_signups, start=1)),
            f"| Total | {sum(result.weekly_signups):,} |",
            "",
            f"Emails to the same merchant are at least {settings.min_gap_days:g} days apart. Every rate, lift and "
            "revenue below rests on placeholder settings (listed at the end), so read them as directions, not forecasts.",
            "",
        ]
        for segment in SEGMENT_TEXT:
            lines += _segment_section(settings, segment, result.outcomes[segment], result.baselines[segment])
        lines += _loop_section(result.loop)
    lines += [
        "## Placeholders",
        "",
        "These numbers are made up and should be replaced with real data:",
        "",
        *(f"- {s.note} ({s.key} = {s.value:g})" for s in settings.entries if s.placeholder),
        *(
            [f"- The hidden quality of each of the stand-in writer's {len(settings.prewritten_subjects)} subjects and {len(settings.prewritten_bodies)} bodies (prewritten.toml)."]
            if any(v.placeholder for v in (*settings.prewritten_subjects, *settings.prewritten_bodies))
            else []
        ),
        "",
    ]
    return "\n".join(lines)


def _segment_section(settings: Settings, segment: Segment, outcomes: "dict[Approach, SegmentOutcome]", baseline: SegmentOutcome) -> list[str]:
    """One segment's results for every approach and its holdout baseline, then how the emails that
    went out were scored, with the holdout's ghost sends apart."""
    label, trigger, goal, done = SEGMENT_TEXT[segment]
    behaviour = settings.segments[segment]
    paying = segment is Segment.TRIALIST
    lines = [
        f"### {label}: {goal}",
        "",
        f"Reached means the merchant {done} within {behaviour.horizon_days:g} days of {trigger}. "
        f"Paid means it paid within {settings.paid_window_days:g} days of {trigger}"
        + (f"; each payment is ${settings.monthly_price:,.0f} of first-month revenue." if paying else "."),
        "",
        "| Approach | Merchants judged | Reached the goal | True lift (pts) | Paid within "
        f"{settings.paid_window_days:g} days |" + (" First-month revenue |" if paying else ""),
        "|---|---|---|---|---|" + ("---|" if paying else ""),
    ]
    for approach, o in outcomes.items():
        lift = "reference" if approach is Approach.NO_EMAIL else f"{o.true_lift * 100:+.1f}"
        row = f"| {APPROACH_LABEL[approach]} | {o.counted:,} | {o.reached_share:.1%} | {lift} | {o.paid_share:.1%} |"
        lines.append(row + (f" ${o.first_month_revenue:,.0f} |" if paying else ""))
    held = f"| {HOLDOUT_LABEL} | {baseline.counted:,} | {baseline.reached_share:.1%} | baseline | {baseline.paid_share:.1%} |"
    lines += [
        held + (f" ${baseline.first_month_revenue:,.0f} |" if paying else ""),
        "",
        f"Approaches count only emailed merchants. The {settings.holdout_share:.0%} held out for life are never emailed; "
        "their goal rate is the baseline real data would measure. "
        f"With {baseline.counted:,} merchants held out, chance alone moves its rate by about ±{_margin(baseline):.1f} points.",
        "",
        f"An email is a hit if the merchant {done} within {behaviour.miss_window_days:g} days of {MISS_WINDOW_FROM[segment]}, "
        "and a miss once that window has passed without it. Skipped emails were due after the merchant moved on or the trial ended.",
        "",
        "| Approach | Emails sent | Skipped | Hits | Misses |",
        "|---|---|---|---|---|",
        *(
            f"| {APPROACH_LABEL[a]} | {o.emails.sent:,} | {o.emails.skipped:,} | {o.emails.hits:,} | {o.emails.misses:,} |"
            for a, o in outcomes.items()
            if a is not Approach.NO_EMAIL
        ),
        f"| Holdout (ghost sends: nothing sent) | {baseline.emails.sent:,} | {baseline.emails.skipped:,} | – | – |",
        "",
    ]
    return lines


def _loop_section(loop: LoopReport) -> list[str]:
    """What the AI loop has tried, what leads now, and which timing each segment favours."""

    def variants(heading: str, records: list[VariantRecord]) -> list[str]:
        out = [f"| {heading} | Hidden quality | Sends | Human clicks | Now |", "|---|---|---|---|---|"]
        for i, v in enumerate(records):
            words = v.text + (f" **[{v.cta}]**" if v.cta else "") + (" (your first draft)" if i == 0 else "")
            status = "retired" if v.retired else "leading" if v.leading else "in play"
            out.append(f"| {words} | {v.quality:g} | {v.sends:,} | {_share(v.clicks, v.sends)} | {status} |")
        return out

    lines = [
        "### What the AI loop is sending",
        "",
        "Idle tests subjects and bodies against each other and learns from human clicks. Drafters and Trialists "
        "get whichever Idle subject and body lead. Hidden quality is visible only because this is a simulation: "
        "100 is your first draft, and every other number is a placeholder.",
        "",
        *variants("Subject", loop.subjects),
        "",
        *variants("Body", loop.bodies),
        "",
        "Each segment learns timing from every emailed merchant assigned it, judged when the horizon closes. "
        "With a few hundred merchants per timing, the one ahead so far may still be ahead by chance.",
        "",
        "| Segment | Timing | Merchants judged | Reached the goal | Now |",
        "|---|---|---|---|---|",
    ]
    for segment, timings in loop.timings.items():
        for t in timings:
            lines.append(f"| {SEGMENT_TEXT[segment].label} | {t.label} | {t.assigned:,} | {_share(t.reached, t.assigned)} | {'ahead so far' if t.leading else ''} |")
    return lines + [""]


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "–"


def _margin(outcome: SegmentOutcome) -> float:
    """The 95% margin of a share, in points: how far chance alone can move it at this sample size."""
    p, n = outcome.reached_share, outcome.counted
    return 1.96 * (p * (1 - p) / n) ** 0.5 * 100 if n else 0.0
