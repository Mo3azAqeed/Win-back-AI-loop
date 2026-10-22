"""The report a non-technical reader can follow."""

from typing import TYPE_CHECKING

from winback.lifecycle import Approach
from winback.settings import Settings
from winback.world import Segment

if TYPE_CHECKING:
    from winback.run import StartResult

SEGMENT_LABEL = {Segment.IDLE: "Idle", Segment.DRAFTER: "Drafter", Segment.TRIALIST: "Trialist"}
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
    for segment, behaviour, trigger in (
        (Segment.IDLE, settings.idle, "signup"),
        (Segment.DRAFTER, settings.drafter, "the draft is started"),
        (Segment.TRIALIST, settings.trialist, "publishing"),
    ):
        draft = settings.first_drafts[segment.value]
        lines += [
            f"### {SEGMENT_LABEL[segment]}",
            "",
            f"Sent {behaviour.hand_written_after_days:g} days after {trigger}.",
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
            "### Idle: start a draft",
            "",
            f"Each new signup counts as reached if it starts a store draft within {settings.idle_horizon_days:g} days of signing up.",
            "",
            "| Approach | Merchants counted | Started a draft | True lift (pts) | Emails sent | Skipped (drafted first) |",
            "|---|---|---|---|---|---|",
        ]
        for approach, o in result.idle.items():
            lift = "baseline" if approach is Approach.NO_EMAIL else f"{o.true_lift * 100:+.1f}"
            lines.append(f"| {APPROACH_LABEL[approach]} | {o.counted:,} | {o.reached_share:.1%} | {lift} | {o.sent:,} | {o.skipped:,} |")
        lines += [
            "",
            "### Segments with your first drafts",
            "",
            f"Emails are at least {settings.min_gap_days:g} days apart; an email is skipped if the merchant moved on before it was due.",
            "",
            "| Segment | Merchants entered | Emails sent | Skipped (moved on first) |",
            "|---|---|---|---|",
            *(
                f"| {SEGMENT_LABEL[s]} | {t.entered:,} | {t.sent:,} | {t.skipped:,} |"
                for s, t in result.traffic[Approach.HAND_WRITTEN].items()
            ),
            "",
        ]
    lines += [
        "## Placeholders",
        "",
        "These numbers are made up and should be replaced with real data:",
        "",
        *(f"- {s.note} ({s.key} = {s.value:g})" for s in settings.entries if s.placeholder),
        "",
    ]
    return "\n".join(lines)
