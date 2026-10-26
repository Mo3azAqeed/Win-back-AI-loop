"""The report a non-technical reader can follow."""

import statistics
from typing import TYPE_CHECKING, NamedTuple

from winback.lifecycle import Approach, OfferSummary, SegmentOutcome
from winback.loop import LoopReport, VariantRecord
from winback.offers import Offer
from winback.replays import Replays
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


def render(settings: Settings, seed: int, by_start: "dict[int, StartResult]", replays: dict[int, Replays]) -> str:
    lines = [
        "# Win-back simulation report",
        "",
        f"Seed: {seed}. Every number marked as a placeholder below is made up.",
        "",
        *_summary(settings, replays),
        *_replays_section(settings, replays),
        f"The rest of this report is the first replay (seed {seed}) in full.",
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
            lines += _segment_section(settings, segment, result.outcomes[segment], result.pushed[segment], result.baselines[segment])
            if segment is Segment.TRIALIST:
                lines += _offers_section(settings, result.offers)
        lines += _loop_section(settings, result.loop)
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


def _segment_section(
    settings: Settings, segment: Segment, outcomes: "dict[Approach, SegmentOutcome]", pushed: "dict[Approach, SegmentOutcome]", baseline: SegmentOutcome
) -> list[str]:
    """One segment's results for every approach, the merchants an earlier email pushed into it, and its
    holdout baseline; then how every email that went out was scored, with the holdout's ghost sends apart."""
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
        extra = pushed[approach]
        if extra.counted:
            row = f"| {APPROACH_LABEL[approach]}: pushed here by an earlier email | {extra.counted:,} | {extra.reached_share:.1%} | – | {extra.paid_share:.1%} |"
            lines.append(row + (f" ${extra.first_month_revenue:,.0f} |" if paying else ""))
    held = f"| {HOLDOUT_LABEL} | {baseline.counted:,} | {baseline.reached_share:.1%} | baseline | {baseline.paid_share:.1%} |"
    lines += [
        held + (f" ${baseline.first_month_revenue:,.0f} |" if paying else ""),
        "",
        "Every approach is judged on the same merchants: the emailed ones who would be here with no email at all. "
        + (
            "Merchants who are here only because an earlier email pushed them on are that email's win, counted in the "
            "segment before, so they get their own line and no lift. "
            if segment is not Segment.IDLE
            else ""
        )
        + f"The {settings.holdout_share:.0%} held out for life are never emailed; "
        "their goal rate is the baseline real data would measure. "
        f"With {baseline.counted:,} merchants held out, chance alone moves its rate by about ±{_margin(baseline):.1f} points.",
        "",
        f"An email is a hit if the merchant {done} within {behaviour.miss_window_days:g} days of {MISS_WINDOW_FROM[segment]}, "
        "and a miss once that window has passed without it. Skipped emails were due after the merchant moved on or the trial ended.",
        "",
        "| Approach | Emails sent | Skipped | Hits | Misses |",
        "|---|---|---|---|---|",
        *(
            f"| {APPROACH_LABEL[a]} | {e.sent:,} | {e.skipped:,} | {e.hits:,} | {e.misses:,} |"
            for a, o in outcomes.items()
            if a is not Approach.NO_EMAIL
            for e in [o.emails + pushed[a].emails]  # every email sent in this segment, whoever it went to
        ),
        f"| Holdout (ghost sends: nothing sent) | {baseline.emails.sent:,} | {baseline.emails.skipped:,} | – | – |",
        "",
    ]
    return lines


def _offer_labels(settings: Settings) -> dict[Offer, str]:
    offers = settings.offers
    return {
        Offer.NONE: "No offer",
        Offer.EXTENSION: f"{offers.extra_trial_days:g} more trial days",
        Offer.DISCOUNT: f"First month {1 - offers.discount_price_share:.0%} off",
    }


def _offers_section(settings: Settings, offers: OfferSummary) -> list[str]:
    """The offers the AI loop's Trialist emails carried, and what the discount cost."""
    labels, price = _offer_labels(settings), settings.monthly_price
    return [
        "Each AI loop Trialist email carries one offer, added as a line to your Trialist first draft. "
        "The hand-written email never carries one.",
        "",
        "Emails sent count the Trialists entered by the end of the weeks of signups.",
        "",
        "| Offer | Line added to the email | Emails sent |",
        "|---|---|---|",
        *(f"| {labels[o]} | {settings.offers.lines[o] or '–'} | {offers.sent[o]:,} |" for o in Offer),
        "",
        f"{offers.discounted_payers:,} Trialists paid with the discount; {offers.would_have_paid_anyway:,} of them "
        f"would have paid the full ${price:,.0f} with no email.",
        "",
    ]


def _loop_section(settings: Settings, loop: LoopReport) -> list[str]:
    """What the AI loop has tried, what leads now, and which timing and offer each segment favours."""

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
        "Idle tests subjects and bodies against each other and learns from human clicks. Hidden quality is "
        "visible only because this is a simulation: 100 is your first draft, and every other number is a placeholder.",
        "",
        *variants("Subject", loop.subjects),
        "",
        *variants("Body", loop.bodies),
        "",
        f"Carry-over from Idle: {loop.carry_over:.0%}. Drafters and Trialists get their own first drafts, plus this share "
        "of the edge the Idle leader has over your Idle first draft"
        + (
            ", so any win over the hand-written email there comes from what the AI loop tests in that segment."
            if loop.carry_over == 0
            else ". That edge is assumed, not tested on Drafters or Trialists."
        ),
        "",
        "| Segment | Email | Sends | Human clicks |",
        "|---|---|---|---|",
        *(
            f"| {SEGMENT_TEXT[segment].label} | {c.subject}: {c.body} **[{c.cta}]** | {c.sends:,} | {_share(c.clicks, c.sends)} |"
            for segment, c in loop.segment_copy.items()
        ),
        "",
        "Each segment learns timing from every merchant assigned it, judged when the horizon closes, "
        "including merchants who acted before their email went out (the holdout aside). "
        "With a few hundred merchants per timing, the one ahead so far may still be ahead by chance.",
        "",
        "| Segment | Timing | Merchants judged | Reached the goal | Now |",
        "|---|---|---|---|---|",
    ]
    for segment, timings in loop.timings.items():
        for t in timings:
            lines.append(f"| {SEGMENT_TEXT[segment].label} | {t.label} | {t.assigned:,} | {_share(t.reached, t.assigned)} | {'ahead so far' if t.leading else ''} |")
    labels = _offer_labels(settings)
    lines += [
        "",
        "Trialist offers learn the same way, from the first-month revenue of every Trialist assigned them, "
        "so a discounted payment counts as half.",
        "",
        "| Offer | Trialists judged | First-month revenue per Trialist | Now |",
        "|---|---|---|---|",
        *(
            f"| {labels[o.offer]} | {o.assigned:,} | "
            + (f"${o.revenue_share * settings.monthly_price / o.assigned:,.2f}" if o.assigned else "–")
            + f" | {'ahead so far' if o.leading else ''} |"
            for o in loop.offers
        ),
    ]
    return lines + [""]


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "–"


def _margin(outcome: SegmentOutcome) -> float:
    """The 95% margin of a share, in points: how far chance alone can move it at this sample size."""
    p, n = outcome.reached_share, outcome.counted
    return 1.96 * (p * (1 - p) / n) ** 0.5 * 100 if n else 0.0


SHORT_LABEL = {Approach.NO_EMAIL: "No email", Approach.HAND_WRITTEN: "Hand-written email", Approach.AI_LOOP: "AI loop"}
# Chart lines, in the order drawn: no email (the zero line), the hand-written email, the AI loop.
CHART_COLOURS = {Approach.NO_EMAIL: ("#9ca3af", "Grey"), Approach.HAND_WRITTEN: ("#f59e0b", "Orange"), Approach.AI_LOOP: ("#2563eb", "Blue")}


def _average(values: list[float]) -> float:
    return statistics.fmean(values)


def _middle_90(values: list[float]) -> tuple[float, float]:
    """Where the middle 90% of replays fall: from the 5th to the 95th percentile."""
    if len(values) < 2:
        return values[0], values[0]
    cuts = statistics.quantiles(values, n=20, method="inclusive")
    return cuts[0], cuts[-1]


def _lifts(replays: Replays, segment: Segment, approach: Approach) -> list[float]:
    return [s.lifts[segment][approach] * 100 for s in replays.stats]


def _wins(replays: Replays, segment: Segment) -> int:
    return sum(a > h for a, h in zip(_lifts(replays, segment, Approach.AI_LOOP), _lifts(replays, segment, Approach.HAND_WRITTEN)))


def _weekly(replays: Replays, segment: Segment, approach: Approach) -> list[float]:
    """The average across replays of the cumulative true lift by the end of each week, in points."""
    weeks = len(replays.stats[0].weekly[segment][approach])
    return [_average([s.weekly[segment][approach][w] * 100 for s in replays.stats]) for w in range(weeks)]


def _ahead_from(replays: Replays, segment: Segment) -> int | None:
    """The week from which the AI loop's average cumulative lift stays above the hand-written email's, if any."""
    ai, hand = _weekly(replays, segment, Approach.AI_LOOP), _weekly(replays, segment, Approach.HAND_WRITTEN)
    week = None
    for w in range(len(ai), 0, -1):
        if ai[w - 1] <= hand[w - 1]:
            break
        week = w
    return week


def _did_better(replays: Replays, segment: Segment) -> bool:
    """Higher average true lift, and ahead in more than half of the replays."""
    ai, hand = _lifts(replays, segment, Approach.AI_LOOP), _lifts(replays, segment, Approach.HAND_WRITTEN)
    return _average(ai) > _average(hand) and _wins(replays, segment) * 2 > len(ai)


def _summary(settings: Settings, replays: dict[int, Replays]) -> list[str]:
    """The plain-English summary, written from the results."""
    count = len(next(iter(replays.values())).seeds)
    lines = [
        "## Summary",
        "",
        f"The same {settings.weeks} weeks were replayed {count:,} times with different luck. "
        "Every number rests on placeholder settings, so read it as a direction, not a forecast.",
        "",
    ]
    for start, r in replays.items():
        better = [s for s in Segment if _did_better(r, s)]
        lines += [f"**From {start:,} merchants**, the AI loop did better than the hand-written email in {len(better)} of {len(Segment)} segments.", ""]
        for segment in Segment:
            ai, hand = _average(_lifts(r, segment, Approach.AI_LOOP)), _average(_lifts(r, segment, Approach.HAND_WRITTEN))
            verdict = "did better" if segment in better else "did no better"
            week = _ahead_from(r, segment)
            sentence = (
                f"- In {SEGMENT_TEXT[segment].label} the AI loop {verdict}: {ai:+.1f} points against {hand:+.1f} for the hand-written email, "
                f"ahead in {_wins(r, segment):,} of {count:,} replays"
                + (f", ahead from week {week} on average" if week is not None else "")
                + "."
            )
            if segment is Segment.TRIALIST:
                money = {a: _average([s.revenue[a] for s in r.stats]) for a in (Approach.AI_LOOP, Approach.HAND_WRITTEN)}
                sentence += (
                    f" Trialists brought ${money[Approach.AI_LOOP]:,.0f} of first-month revenue per replay with the AI loop "
                    f"against ${money[Approach.HAND_WRITTEN]:,.0f} with the hand-written email."
                )
            lines.append(sentence)
        lines.append("")
    if len(replays) > 1:
        (small, a), (large, b) = sorted(replays.items())[0], sorted(replays.items())[-1]

        def edge(r: Replays, segment: Segment) -> float:
            return _average(_lifts(r, segment, Approach.AI_LOOP)) - _average(_lifts(r, segment, Approach.HAND_WRITTEN))

        moves = ", ".join(f"{SEGMENT_TEXT[s].label} {edge(a, s):+.1f} to {edge(b, s):+.1f}" for s in Segment)
        lines += [f"Starting from {large:,} merchants instead of {small:,}, the AI loop's edge over the hand-written email, in points, moved: {moves}.", ""]
    lines += [
        "No lessons are written yet (they arrive with #9), so none can be false. Your original open-and-click idea joins the comparison with #10.",
        "",
    ]
    return lines


def _replays_section(settings: Settings, replays: dict[int, Replays]) -> list[str]:
    """Averages, middle-90% ranges and wins per segment, Trialist revenue, and a weekly chart per segment."""
    count = len(next(iter(replays.values())).seeds)
    lines = [
        f"## Across {count:,} replays",
        "",
        "True lift is in points against no email, on the same merchants (see each segment below). The middle 90% "
        "leaves out the luckiest and unluckiest 5% of replays on each side.",
        "",
    ]
    for start, r in replays.items():
        lines += [
            f"### From {start:,} merchants",
            "",
            "| Segment | Approach | Average true lift (pts) | Middle 90% of replays (pts) | AI loop beat the hand-written email |",
            "|---|---|---|---|---|",
        ]
        for segment in Segment:
            for approach in (Approach.HAND_WRITTEN, Approach.AI_LOOP):
                values = _lifts(r, segment, approach)
                low, high = _middle_90(values)
                won = f"{_wins(r, segment):,} of {count:,}" if approach is Approach.AI_LOOP else "–"
                lines.append(f"| {SEGMENT_TEXT[segment].label} | {SHORT_LABEL[approach]} | {_average(values):+.1f} | {low:+.1f} to {high:+.1f} | {won} |")
        lines += [
            "",
            f"Trialist first-month revenue, average per replay (${settings.monthly_price:,.0f} a payment, ${settings.monthly_price * settings.offers.discount_price_share:,.0f} with the discount):",
            "",
            "| Approach | Average first-month revenue |",
            "|---|---|",
            *(f"| {SHORT_LABEL[a]} | ${_average([s.revenue[a] for s in r.stats]):,.0f} |" for a in Approach),
            "",
        ]
        for segment in Segment:
            palette = ", ".join(colour for colour, _ in CHART_COLOURS.values())
            weeks = len(r.stats[0].weekly[segment][Approach.AI_LOOP])
            lines += [
                f"#### {SEGMENT_TEXT[segment].label}: true lift so far, week by week",
                "",
                "```mermaid",
                f'%%{{init: {{"themeVariables": {{"xyChart": {{"plotColorPalette": "{palette}"}}}}}}}}%%',
                "xychart-beta",
                f'    title "{SEGMENT_TEXT[segment].label}: cumulative true lift (pts)"',
                f'    x-axis "Week" [{", ".join(str(w) for w in range(1, weeks + 1))}]',
                '    y-axis "True lift (pts)"',
                *(f"    line [{', '.join(f'{v:.2f}' for v in _weekly(r, segment, a))}]" for a in CHART_COLOURS),
                "```",
                "",
                ". ".join(f"{name}: {SHORT_LABEL[a].lower()}" for a, (_, name) in CHART_COLOURS.items())
                + ". Each week counts the merchants who would have entered the segment by then with no email.",
                "",
            ]
    return lines
