"""The report a non-technical reader can follow."""

from typing import TYPE_CHECKING

from winback.idle import APPROACH_LABEL
from winback.settings import Settings

if TYPE_CHECKING:
    from winback.run import StartResult


def render(settings: Settings, seed: int, by_start: "dict[int, StartResult]") -> str:
    idle_draft = settings.first_drafts["idle"]
    lines = [
        "# Win-back simulation report",
        "",
        f"Seed: {seed}. Every number marked as a placeholder below is made up.",
        "",
        "## Your first draft for Idle merchants",
        "",
        f"Sent {settings.idle_first_draft_after_days:g} days after signup.",
        "",
        f"> **Subject:** {idle_draft.subject}",
        ">",
        f"> {idle_draft.body}",
        ">",
        f"> **[{idle_draft.cta}]**",
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
            f"Judged on whether each new signup starts a draft within {settings.idle_judge_days:g} days.",
            "",
            "| Approach | Merchants judged | Started a draft | True lift (pts) | Emails sent | Skipped (drafted first) |",
            "|---|---|---|---|---|---|",
        ]
        for approach, o in result.idle.items():
            lift = "baseline" if approach == "no_email" else f"{o.true_lift * 100:+.1f}"
            lines.append(f"| {APPROACH_LABEL[approach]} | {o.judged:,} | {o.share:.1%} | {lift} | {o.sent:,} | {o.skipped:,} |")
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
