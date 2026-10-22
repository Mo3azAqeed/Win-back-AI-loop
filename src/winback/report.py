"""The report a non-technical reader can follow."""

from typing import TYPE_CHECKING

from winback.lifecycle import Approach, SegmentOutcome
from winback.settings import Settings
from winback.segments import Segment

if TYPE_CHECKING:
    from winback.run import StartResult

# How each segment is named in the report, what starts its clock, and its goal action (to do, and done).
SEGMENT_TEXT = {
    Segment.IDLE: ("Idle", "entering Idle (signup, for new merchants)", "start a draft", "started a draft"),
    Segment.DRAFTER: ("Drafter", "saving the draft", "publish", "published"),
    Segment.TRIALIST: ("Trialist", "publishing", "pay", "paid"),
}
APPROACH_LABEL = {Approach.NO_EMAIL: "No email", Approach.HAND_WRITTEN: "Hand-written email (your first draft)"}
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
    for segment, (label, trigger, _, _) in SEGMENT_TEXT.items():
        draft = settings.first_drafts[segment.value]
        lines += [
            f"### {label}",
            "",
            f"Sent {settings.segments[segment].hand_written_after_days:g} days after {trigger}.",
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
            f"Emails to the same merchant are at least {settings.min_gap_days:g} days apart.",
            "",
        ]
        for segment in SEGMENT_TEXT:
            lines += _segment_section(settings, segment, result.outcomes[segment])
    lines += [
        "## Placeholders",
        "",
        "These numbers are made up and should be replaced with real data:",
        "",
        *(f"- {s.note} ({s.key} = {s.value:g})" for s in settings.entries if s.placeholder),
        "",
    ]
    return "\n".join(lines)


def _segment_section(settings: Settings, segment: Segment, outcomes: "dict[Approach, SegmentOutcome]") -> list[str]:
    """One segment's results for every approach, then how the emails that went out were scored."""
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
        "| Approach | Merchants counted | Reached the goal | True lift (pts) | Paid within "
        f"{settings.paid_window_days:g} days |" + (" First-month revenue |" if paying else ""),
        "|---|---|---|---|---|" + ("---|" if paying else ""),
    ]
    for approach, o in outcomes.items():
        lift = "reference" if approach is Approach.NO_EMAIL else f"{o.true_lift * 100:+.1f}"
        row = f"| {APPROACH_LABEL[approach]} | {o.counted:,} | {o.reached_share:.1%} | {lift} | {o.paid_share:.1%} |"
        lines.append(row + (f" ${o.revenue:,.0f} |" if paying else ""))
    lines += [
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
        "",
    ]
    return lines
