"""The report a non-technical reader can follow."""

from winback.settings import Settings


def render(settings: Settings, seed: int, weekly_signups: list[int], already_paying: int) -> str:
    lines = [
        "# Win-back simulation report",
        "",
        f"Seed: {seed}. Every number marked as a placeholder below is made up.",
        "",
        "## Merchants",
        "",
        f"Merchants today: {settings.start_merchants:,}",
        f"Already paying (not simulated): {already_paying:,}",
        "",
        "| Week | New signups |",
        "|---|---|",
        *(f"| {week} | {count:,} |" for week, count in enumerate(weekly_signups, start=1)),
        f"| Total | {sum(weekly_signups):,} |",
        "",
        "## Placeholders",
        "",
        "These numbers are made up and should be replaced with real data:",
        "",
        *(f"- {s.note} ({s.key} = {s.value:g})" for s in settings.all if s.placeholder),
        "",
    ]
    return "\n".join(lines)
