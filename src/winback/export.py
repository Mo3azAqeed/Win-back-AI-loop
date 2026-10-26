"""A run's results as data, for the web app: what the report says, in a shape a page can draw."""

import math
from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, Any

from winback.lifecycle import Approach, EmailFate
from winback.loop import CopyChange, LoopReport, VariantRecord
from winback.offers import Offer
from winback.replays import Replays
from winback.report import SEGMENT_TEXT, SHORT_LABEL, offer_labels, summary_sentences
from winback.segments import Segment
from winback.settings import Settings
from winback.world import DAYS_PER_WEEK

if TYPE_CHECKING:  # run.py imports this module's caller
    from winback.run import RunResult, StartResult


def run_data(settings: Settings, result: "RunResult", *, seed: int, created: date) -> dict[str, Any]:
    """Everything the web app shows for one run. Lifts are in points; the funnel and the emails come from the
    first replay, shown in full in the report, and the rest from every replay."""
    replays = next(iter(result.replays.values()))
    return {
        "seed": seed,
        "created": created.isoformat(),
        "replays": len(replays.seeds),
        "weeks": settings.weeks,
        "summary": summary_sentences(settings, result.replays),
        "first_drafts": [
            {
                "segment": s.value,
                "label": SEGMENT_TEXT[s].label,
                "subject": settings.first_drafts[s.value].subject,
                "body": settings.first_drafts[s.value].body,
                "cta": settings.first_drafts[s.value].cta,
                "send_after_days": settings.segments[s].hand_written_after_days,
            }
            for s in Segment
        ],
        "starts": [_start(settings, start, r, result.by_start[start]) for start, r in result.replays.items()],
        "placeholders": sum(e.placeholder for e in settings.entries),
    }


def _start(settings: Settings, merchants: int, replays: Replays, detail: "StartResult") -> dict[str, Any]:
    labels = offer_labels(settings)
    loop = detail.loop
    offer_records = {o.offer: o for o in loop.offers}
    return {
        "merchants": merchants,
        "segments": [
            {
                "segment": s.value,
                "label": SEGMENT_TEXT[s].label,
                "goal": SEGMENT_TEXT[s].goal,
                "done": SEGMENT_TEXT[s].done,
                "horizon_days": settings.segments[s].horizon_days,
                "approaches": [
                    {"approach": a.value, "label": SHORT_LABEL[a], "average": replays.average(s, a), "low": replays.middle_90(s, a)[0], "high": replays.middle_90(s, a)[1]}
                    for a in Approach
                ],
                "ai_ahead": replays.wins(s),
                "ties": replays.ties(s),
                "ahead_from_week": replays.ahead_from(s),
                "ai_did_better": replays.did_better(s),
                "weekly": {a.value: replays.weekly(s, a) for a in Approach},
                "weeks": _weeks(detail, s, len(replays.weekly(s, Approach.AI_LOOP))),
                "funnel": {
                    a.value: {
                        "merchants": detail.outcomes[s][a].counted + detail.pushed[s][a].counted,
                        "reached": detail.outcomes[s][a].reached + detail.pushed[s][a].reached,
                    }
                    for a in Approach
                },
            }
            for s in Segment
        ],
        "revenue": {a.value: replays.revenue(a) for a in Approach},
        "loop": {
            "carry_over": loop.carry_over,
            "subjects": [_variant(v) for v in loop.subjects],
            "bodies": [_variant(v) for v in loop.bodies],
            "segment_copy": [
                {"segment": s.value, "label": SEGMENT_TEXT[s].label, "subject": c.subject, "body": c.body, "cta": c.cta, "sends": c.sends, "clicks": c.clicks}
                for s, c in loop.segment_copy.items()
            ],
            "timings": [
                {"segment": s.value, "label": SEGMENT_TEXT[s].label, "timing": t.label, "assigned": t.assigned, "reached": t.reached, "leading": t.leading}
                for s, timings in loop.timings.items()
                for t in timings
            ],
            "offers": [
                {
                    "offer": o.value,
                    "label": labels[o],
                    "line": settings.offers.lines[o],
                    "sent": detail.offers.sent[o],
                    "assigned": offer_records[o].assigned,
                    "revenue_per_trialist": offer_records[o].revenue_share * settings.monthly_price / offer_records[o].assigned if offer_records[o].assigned else None,
                    "leading": offer_records[o].leading,
                }
                for o in Offer
            ],
            "discounted_payers": detail.offers.discounted_payers,
            "would_have_paid_anyway": detail.offers.would_have_paid_anyway,
        },
    }


def _variant(v: VariantRecord) -> dict[str, Any]:
    status = "retired" if v.retired else "leading" if v.leading else "in play"
    return {"text": v.text, "cta": v.cta, "quality": v.quality, "sends": v.sends, "clicks": v.clicks, "status": status}


def _week_of(day: float) -> int:
    return max(1, math.ceil(day / DAYS_PER_WEEK))


def _weeks(detail: "StartResult", segment: Segment, weeks: int) -> list[dict[str, Any]]:
    """Week by week in the first replay: how each approach's emails sent that week did (clicks, and how many
    of those merchants went on to the goal action), the email the AI loop was sending, and for Idle what
    it wrote and dropped that week."""
    tallies: dict[Approach, list[Counter[str]]] = {a: [Counter() for _ in range(weeks)] for a in (Approach.HAND_WRITTEN, Approach.AI_LOOP)}
    offers: list[Counter[str]] = [Counter() for _ in range(weeks)]
    for approach, by_week in tallies.items():
        for journey in detail.journeys[approach]:
            for stay in journey.stays:
                if stay.segment is not segment or stay.email is not EmailFate.SENT or stay.email_sent_at is None:
                    continue
                week = _week_of(stay.email_sent_at)
                if week > weeks:
                    continue
                by_week[week - 1].update(sent=1, clicks=int(stay.clicked), goal_actions=int(stay.left is not None))
                if approach is Approach.AI_LOOP and stay.offer is not None:
                    offers[week - 1][stay.offer.value] += 1
    loop = detail.loop
    out = []
    for week in range(1, weeks + 1):
        ai: dict[str, Any] = {key: tallies[Approach.AI_LOOP][week - 1][key] for key in ("sent", "clicks", "goal_actions")}
        ai["leading"] = _leading(loop, segment, week)
        ai["offers"] = dict(offers[week - 1])
        changes = [c for c in loop.history if _week_of(c.day) == week] if segment is Segment.IDLE else []
        ai["written"] = [_change(c) for c in changes if c.change == "written"]
        ai["dropped"] = [_change(c) for c in changes if c.change == "dropped"]
        hand = {key: tallies[Approach.HAND_WRITTEN][week - 1][key] for key in ("sent", "clicks", "goal_actions")}
        out.append({"week": week, "hand": hand, "ai": ai})
    return out


def _leading(loop: LoopReport, segment: Segment, week: int) -> dict[str, str]:
    """The email the AI loop was sending to this segment at the end of the week: Idle's leaders, or the
    segment's own first draft."""
    if segment is not Segment.IDLE:
        own = loop.segment_copy[segment]
        return {"subject": own.subject, "body": own.body, "cta": own.cta}
    known = [w for w in loop.weekly_leaders if w.week <= week]
    leaders = known[-1] if known else loop.weekly_leaders[0]
    return {"subject": leaders.subject, "body": leaders.body, "cta": leaders.cta}


def _change(c: CopyChange) -> dict[str, Any]:
    return {"part": c.slot, "text": c.text, "cta": c.cta, "sends": c.sends, "clicks": c.clicks, "by": c.by}
