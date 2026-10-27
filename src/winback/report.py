"""The report a non-technical reader can follow."""

from typing import TYPE_CHECKING, NamedTuple

from winback.lifecycle import Approach
from winback.loop import LoopReport, VersionRecord
from winback.outcomes import OfferSummary, SegmentOutcome
from winback.replays import Replays
from winback.segments import Segment
from winback.settings import Settings
from winback.trialist import MISS_WINDOW_FROM, Offer, offer_labels
from winback.world import week_of

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
APPROACH_LABEL = {Approach.NO_EMAIL: "No email", Approach.HAND_WRITTEN: "Hand-written email", Approach.AI_LOOP: "AI loop"}
HOLDOUT_LABEL = "Holdout (never emailed)"


def _row_label(approach: Approach) -> str:
    """An approach's name in a segment's tables, which come after your first drafts."""
    return APPROACH_LABEL[approach] + (" (your first draft)" if approach is Approach.HAND_WRITTEN else "")


def render(settings: Settings, seed: int, by_start: "dict[int, StartResult]", replays: dict[int, Replays], writer: list[str] | None = None) -> str:
    """The whole report. `writer` says who wrote and judged the AI loop's words when the real writer did."""
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
        *(["## Writer and judge", "", *writer, ""] if writer else []),
        "## Placeholders",
        "",
        "These numbers are made up and should be replaced with real data:",
        "",
        # The writer's settings matter only when the real writer and judge did the writing.
        *(f"- {s.note} ({s.key} = {s.value:g})" for s in settings.entries if s.placeholder and (writer or not s.key.startswith("writer."))),
        *(
            [f"- The hidden quality of each of the stand-in writer's {len(settings.prewritten_subjects)} subjects and {len(settings.prewritten_bodies)} bodies (prewritten.toml)."]
            if not writer and any(v.placeholder for v in (*settings.prewritten_subjects, *settings.prewritten_bodies))
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
        row = f"| {_row_label(approach)} | {o.counted:,} | {o.reached_share:.1%} | {lift} | {o.paid_share:.1%} |"
        lines.append(row + (f" ${o.first_month_revenue:,.0f} |" if paying else ""))
        pushed_here = pushed[approach]
        if pushed_here.counted:
            row = f"| {_row_label(approach)}: pushed here by an earlier email | {pushed_here.counted:,} | {pushed_here.reached_share:.1%} | – | {pushed_here.paid_share:.1%} |"
            lines.append(row + (f" ${pushed_here.first_month_revenue:,.0f} |" if paying else ""))
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
            f"| {_row_label(a)} | {e.sent:,} | {e.skipped:,} | {e.hits:,} | {e.misses:,} |"
            for a, o in outcomes.items()
            if a is not Approach.NO_EMAIL
            for e in [o.emails + pushed[a].emails]  # every email sent in this segment, whoever it went to
        ),
        f"| Holdout (ghost sends: nothing sent) | {baseline.emails.sent:,} | {baseline.emails.skipped:,} | – | – |",
        "",
    ]
    return lines


def _offers_section(settings: Settings, offers: OfferSummary) -> list[str]:
    """The offers the AI loop's Trialist emails carried, and what the discount cost."""
    labels, price = offer_labels(settings.offers), settings.monthly_price
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

    lines = [
        "### What the AI loop is sending",
        "",
        "Idle's email comes in versions. v0 is your first draft and starts as the champion. Each challenger is the "
        "champion with one part changed, and comes with a hypothesis. While a test runs the challenger gets "
        f"{settings.loop.challenger_share:.0%} of Idle's emails and the champion the rest, and the "
        f"test ends at a week's end once the loop is {settings.loop.verdict_confidence:.0%} sure: the challenger won "
        "on human clicks (and is crowned, unless its goal-action rate is clearly worse), the champion won, the two "
        f"are the same (within {settings.loop.same_margin * 100:g} click point), or, after {settings.loop.test_max_weeks} weeks "
        f"or {settings.loop.test_max_sends:,} emails for either, too close to call: "
        + ("the version ahead on clicks stays, kept but not proven. " if settings.loop.keep_ahead_at_limit else "the champion stays. ")
        + "Hidden quality is visible only because this is a simulation: 100 is your first draft, and every other number is a placeholder.",
        "",
        "#### Versions",
        "",
        "| Version | Subject | Body | Changed | Hidden quality (subject, body) | Written by | From week | Now | Sends | Human clicks |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *(
            f"| v{v.number} | {v.subject} | {v.body} **[{v.cta}]** | {v.changed or 'your email'} | {v.quality[0]:g}, {v.quality[1]:g} | {v.by} | "
            f"{week_of(v.introduced_day)} | {_status(v)} | {v.sends:,} | {_share(v.clicks, v.sends)} |"
            for v in loop.versions
        ),
        "",
        *(
            [f"Champion at the end of week {loop.weekly_leaders[-1].week}: v{loop.weekly_leaders[-1].champion}. Week by week: "
             + ", ".join(f"{w.week}: v{w.champion}" + (f" against v{w.challenger}" if w.challenger is not None else "") for w in loop.weekly_leaders) + ".", ""]
            if loop.weekly_leaders
            else []
        ),
        "#### Playbook",
        "",
        "Every test, newest last: what the challenger changed and why, the evidence from the test itself (clicks are "
        "known at once; goal actions only once each email's miss window has closed), and the verdict.",
        "",
        "| Test | Weeks | Champion | Challenger | Hypothesis | Champion: sends, clicks, goal actions | Challenger: sends, clicks, goal actions | Ending | Conclusion |",
        "|---|---|---|---|---|---|---|---|---|",
        *(
            f"| {e.test} | {week_of(e.started)}–{week_of(e.ended)} | v{e.champion} | v{e.challenger} | {e.hypothesis} | "
            f"{e.champion_sends:,}, {_share(e.champion_clicks, e.champion_sends)}, {_share(e.champion_goals, e.champion_goals_judged)} | "
            f"{e.challenger_sends:,}, {_share(e.challenger_clicks, e.challenger_sends)}, {_share(e.challenger_goals, e.challenger_goals_judged)} | "
            f"{e.ending.value} | {e.conclusion} |"
            for e in loop.playbook
        ),
        *([] if loop.playbook else ["No test has ended yet."]),
        "",
        "#### Drafters and Trialists borrow what Idle proves",
        "",
        "They run no tests of their own (about 40 emails a week each is too few). When an Idle test is won, the writer "
        "applies the same change to their emails in their own words, and that version replaces theirs with no test.",
        "",
        f"Carry-over from Idle: {loop.carry_over:.0%}. "
        + (
            "How much a borrowed change helps them isn't simulated yet: at 0, a borrowed change gets no simulated boost, so their results are "
            "the same as without it, and any win over the hand-written email there comes from timing (and Trialist offers). "
            "The real effect waits for the judge rating the new words."
            if loop.carry_over == 0
            else "A borrowed change gets this share of the edge the Idle part it came from has over your Idle first draft. "
            "That edge is assumed, not tested on Drafters or Trialists."
        ),
        "",
        "| Segment | Version | Email | Where it came from | From week | Sends | Human clicks |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {SEGMENT_TEXT[segment].label} | v{v.number} | {v.subject}: {v.body} **[{v.cta}]** | "
            + (f"borrowed from Idle test {v.borrowed_from_test} (v{v.idle_version}, new {v.changed})" if v.borrowed_from_test is not None else "your first draft")
            + f" | {week_of(v.day)} | {v.sends:,} | {_share(v.clicks, v.sends)} |"
            for segment, versions in loop.segment_versions.items()
            for v in versions
        ),
        *(
            ["", *(f"- Idle test {n.test}'s change wasn't borrowed by {SEGMENT_TEXT[n.segment].label}s (week {week_of(n.day)}): the writer had no words for it "
                   "there that passed the checks, or the spending cap stopped it, so they kept their email." for n in loop.not_borrowed)]
            if loop.not_borrowed else []
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
    labels = offer_labels(settings.offers)
    lines += [
        "",
        "Trialist offers learn the same way, from the first-month revenue of every Trialist assigned them, "
        "so a discounted payment counts as half.",
        "",
        "| Offer | Trialists judged | First-month revenue per Trialist | Now |",
        "|---|---|---|---|",
        *(
            f"| {labels[o.offer]} | {o.assigned:,} | "
            + (f"${revenue:,.2f}" if (revenue := o.revenue_per_trialist(settings.monthly_price)) is not None else "–")
            + f" | {'ahead so far' if o.leading else ''} |"
            for o in loop.offers
        ),
    ]
    return lines + [""]


def _status(v: VersionRecord) -> str:
    """Where a version stands at the end, with the week it was crowned and the week it was sunset."""
    crowned = f"crowned week {week_of(v.crowned_day)}" if v.crowned_day is not None else ""
    sunset = f"sunset week {week_of(v.sunset_day)}" if v.sunset_day is not None else ""
    now = v.status if v.status != "sunset" else ""
    return ", ".join(part for part in (now, crowned, sunset) if part)


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "–"


def _margin(outcome: SegmentOutcome) -> float:
    """The 95% margin of a share, in points: how far chance alone can move it at this sample size."""
    p, n = outcome.reached_share, outcome.counted
    return 1.96 * (p * (1 - p) / n) ** 0.5 * 100 if n else 0.0


# Chart lines, in the order drawn: no email (the zero line), the hand-written email, the AI loop.
CHART_COLOURS = {Approach.NO_EMAIL: ("#9ca3af", "Grey"), Approach.HAND_WRITTEN: ("#f59e0b", "Orange"), Approach.AI_LOOP: ("#2563eb", "Blue")}


def summary_sentences(settings: Settings, replays: dict[int, Replays]) -> list[str]:
    """The plain-English summary as sentences, without its heading or list marks."""
    return [line.removeprefix("- ") for line in _summary(settings, replays)[1:] if line]


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
        better = [s for s in Segment if r.did_better(s)]
        lines += [f"**From {start:,} merchants**, the AI loop did better than the hand-written email in {len(better)} of {len(Segment)} segments.", ""]
        for segment in Segment:
            ai, hand = r.average(segment, Approach.AI_LOOP), r.average(segment, Approach.HAND_WRITTEN)
            verdict = "did better" if segment in better else "did no better"
            week = r.ahead_from(segment)
            sentence = (
                f"- In {SEGMENT_TEXT[segment].label} the AI loop {verdict}: {ai:+.1f} points against {hand:+.1f} for the hand-written email, "
                f"ahead in {r.wins(segment):,} of {count:,} replays"
                + (f" and tied in {r.ties(segment):,}" if r.ties(segment) else "")
                + (f", ahead from week {week} on average" if week is not None else "")
                + "."
            )
            if segment is Segment.TRIALIST:
                money = {a: r.revenue(a) for a in (Approach.AI_LOOP, Approach.HAND_WRITTEN)}
                sentence += (
                    f" Trialists brought ${money[Approach.AI_LOOP]:,.0f} of first-month revenue per replay with the AI loop "
                    f"against ${money[Approach.HAND_WRITTEN]:,.0f} with the hand-written email."
                )
            lines.append(sentence)
        lines.append("")
    if len(replays) > 1:
        (small, fewer), (large, more) = sorted(replays.items())[0], sorted(replays.items())[-1]

        def edge(r: Replays, segment: Segment) -> float:
            return r.average(segment, Approach.AI_LOOP) - r.average(segment, Approach.HAND_WRITTEN)

        moves = ", ".join(f"{SEGMENT_TEXT[s].label} {edge(fewer, s):+.1f} to {edge(more, s):+.1f}" for s in Segment)
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
            "| Segment | Approach | Average true lift (pts) | Middle 90% of replays (pts) | AI loop against the hand-written email |",
            "|---|---|---|---|---|",
        ]
        for segment in Segment:
            for approach in (Approach.HAND_WRITTEN, Approach.AI_LOOP):
                low, high = r.middle_90(segment, approach)
                won = f"{r.wins(segment):,} ahead, {r.ties(segment):,} tied, of {count:,}" if approach is Approach.AI_LOOP else "–"
                lines.append(f"| {SEGMENT_TEXT[segment].label} | {APPROACH_LABEL[approach]} | {r.average(segment, approach):+.1f} | {low:+.1f} to {high:+.1f} | {won} |")
        lines += [
            "",
            f"Trialist first-month revenue, average per replay (${settings.monthly_price:,.0f} a payment, ${settings.monthly_price * settings.offers.discount_price_share:,.0f} with the discount):",
            "",
            "| Approach | Average first-month revenue |",
            "|---|---|",
            *(f"| {APPROACH_LABEL[a]} | ${r.revenue(a):,.0f} |" for a in Approach),
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
                *(f"    line [{', '.join(f'{v:.2f}' for v in r.weekly(segment, a))}]" for a in CHART_COLOURS),
                "```",
                "",
                ". ".join(f"{name}: {APPROACH_LABEL[a]}" for a, (_, name) in CHART_COLOURS.items())
                + ". Each week counts the merchants whose result was known by then (their horizon had closed), "
                "which is all the AI loop could have learned from; the last week is the segment's true lift.",
                "",
            ]
    return lines
