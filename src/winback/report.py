"""The report a non-technical reader can follow."""

from typing import TYPE_CHECKING

from winback.lifecycle import Approach
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
            f"Emails are at least {settings.min_gap_days:g} days apart; an email is skipped if the merchant moved on, or the trial ended, before it was due.",
            "",
        ]
        for segment, (label, trigger, goal, done) in SEGMENT_TEXT.items():
            lines += [
                f"### {label}: {goal}",
                "",
                f"Reached means the merchant {done} within {settings.segments[segment].horizon_days:g} days of {trigger}.",
                "",
                "| Approach | Merchants counted | Reached the goal | True lift (pts) | Emails sent | Skipped (moved on or trial over) |",
                "|---|---|---|---|---|---|",
            ]
            for approach, o in result.outcomes[segment].items():
                lift = "reference" if approach is Approach.NO_EMAIL else f"{o.true_lift * 100:+.1f}"
                lines.append(f"| {APPROACH_LABEL[approach]} | {o.counted:,} | {o.reached_share:.1%} | {lift} | {o.emails.sent:,} | {o.emails.skipped:,} |")
            lines.append("")
    lines += [
        "## Placeholders",
        "",
        "These numbers are made up and should be replaced with real data:",
        "",
        *(f"- {s.note} ({s.key} = {s.value:g})" for s in settings.entries if s.placeholder),
        "",
    ]
    return "\n".join(lines)
