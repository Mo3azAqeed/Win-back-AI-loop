"""The report a non-technical reader can follow."""

from typing import TYPE_CHECKING

from winback.settings import Settings

if TYPE_CHECKING:
    from winback.run import StartResult


def render(settings: Settings, seed: int, by_start: "dict[int, StartResult]") -> str:
    lines = ["# Win-back simulation report", "", f"Seed: {seed}. Every number marked as a placeholder below is made up.", ""]
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
