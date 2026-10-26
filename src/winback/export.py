"""A run's results as data, for the web app: what the report says, in a shape a page can draw."""

from datetime import date
from typing import TYPE_CHECKING, Any

from winback.lifecycle import Approach
from winback.loop import VariantRecord
from winback.offers import Offer
from winback.replays import Replays
from winback.report import SEGMENT_TEXT, SHORT_LABEL, offer_labels, summary_sentences
from winback.segments import Segment
from winback.settings import Settings

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
