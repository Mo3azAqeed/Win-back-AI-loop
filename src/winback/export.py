"""A run's results as data, for the web app: what the report says, in a shape a page can draw."""

from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, Any

from winback.lifecycle import Approach, EmailFate
from winback.loop import CopyChange, LoopReport, PlaybookEntry, VariantRecord, VersionRecord
from winback.replays import Replays
from winback.report import APPROACH_LABEL, SEGMENT_TEXT, summary_sentences
from winback.segments import Segment
from winback.settings import Settings
from winback.trialist import Offer, offer_labels
from winback.world import DAYS_PER_WEEK, week_of

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
    labels = offer_labels(settings.offers)  # used by the offers below and by each segment's versions
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
                    {"approach": a.value, "label": APPROACH_LABEL[a], "average": replays.average(s, a), "low": replays.middle_90(s, a)[0], "high": replays.middle_90(s, a)[1]}
                    for a in Approach
                ],
                "ai_ahead": replays.wins(s),
                "ties": replays.ties(s),
                "ahead_from_week": replays.ahead_from(s),
                "ai_did_better": replays.did_better(s),
                "weekly": {a.value: replays.weekly(s, a) for a in Approach},
                "weeks": _weeks(detail, s, len(replays.weekly(s, Approach.AI_LOOP))),
                "versions": _versions(detail, s, labels),
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
            "versions": [_version(v) for v in loop.versions],
            "playbook": [_entry(e) for e in loop.playbook],
            "weekly_champions": [{"week": w.week, "champion": w.champion, "challenger": w.challenger} for w in loop.weekly_leaders],
            "subjects": [_variant(v) for v in loop.subjects],
            "bodies": [_variant(v) for v in loop.bodies],
            "segment_copy": [
                {"segment": s.value, "label": SEGMENT_TEXT[s].label, "subject": c.subject, "body": c.body, "cta": c.cta, "sends": c.sends, "clicks": c.clicks}
                for s, c in loop.segment_copy.items()
            ],
            "segment_versions": [
                {
                    "segment": s.value, "label": SEGMENT_TEXT[s].label, "number": v.number, "subject": v.subject, "body": v.body, "cta": v.cta,
                    "week": week_of(v.day), "borrowed_from_test": v.borrowed_from_test, "idle_version": v.idle_version, "changed": v.changed,
                    "hypothesis": v.hypothesis, "sends": v.sends, "clicks": v.clicks,
                }
                for s, versions in loop.segment_versions.items()
                for v in versions
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
                    "revenue_per_trialist": offer_records[o].revenue_per_trialist(settings.monthly_price),
                    "leading": offer_records[o].leading,
                }
                for o in Offer
            ],
            "discounted_payers": detail.offers.discounted_payers,
            "would_have_paid_anyway": detail.offers.would_have_paid_anyway,
        },
    }


def _version(v: VersionRecord) -> dict[str, Any]:
    return {
        "number": v.number, "subject": v.subject, "body": v.body, "cta": v.cta, "hypothesis": v.hypothesis, "by": v.by, "changed": v.changed,
        "quality": list(v.quality), "status": v.status, "written_week": week_of(v.introduced_day),
        "crowned_week": week_of(v.crowned_day) if v.crowned_day is not None else None, "sunset_week": week_of(v.sunset_day) if v.sunset_day is not None else None,
        "sends": v.sends, "clicks": v.clicks, "goals_judged": v.goals_judged, "goals": v.goals,
    }


def _entry(e: PlaybookEntry) -> dict[str, Any]:
    return {
        "test": e.test, "champion": e.champion, "challenger": e.challenger, "hypothesis": e.hypothesis, "changed": e.changed,
        "started_week": week_of(e.started), "ended_week": week_of(e.ended), "ending": e.ending.value,
        "champion_evidence": {"sends": e.champion_sends, "clicks": e.champion_clicks, "goals_judged": e.champion_goals_judged, "goals": e.champion_goals},
        "challenger_evidence": {"sends": e.challenger_sends, "clicks": e.challenger_clicks, "goals_judged": e.challenger_goals_judged, "goals": e.challenger_goals},
        "chance_better": e.chance_better, "chance_same": e.chance_same, "conclusion": e.conclusion,
    }


def _variant(v: VariantRecord) -> dict[str, Any]:
    status = "sunset" if v.sunset else "leading" if v.leading else "in play"
    return {"text": v.text, "cta": v.cta, "quality": v.quality, "sends": v.sends, "clicks": v.clicks, "status": status}


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
                week = week_of(stay.email_sent_at)
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
        changes = [c for c in loop.history if week_of(c.day) == week] if segment is Segment.IDLE else []
        ai["written"] = [_change(c) for c in changes if c.change == "written"]
        ai["dropped"] = [_change(c) for c in changes if c.change == "dropped"]
        hand = {key: tallies[Approach.HAND_WRITTEN][week - 1][key] for key in ("sent", "clicks", "goal_actions")}
        out.append({"week": week, "hand": hand, "ai": ai})
    return out


def _leading(loop: LoopReport, segment: Segment, week: int) -> dict[str, str]:
    """The email the AI loop was sending to this segment at the end of the week: Idle's leaders, or the
    segment's latest version by then (its first draft, or a change borrowed from Idle)."""
    if segment is not Segment.IDLE:
        own = [v for v in loop.segment_versions[segment] if v.day <= week * DAYS_PER_WEEK][-1]
        return {"subject": own.subject, "body": own.body, "cta": own.cta}
    known = [w for w in loop.weekly_leaders if w.week <= week]
    leaders = known[-1] if known else loop.weekly_leaders[0]
    return {"subject": leaders.subject, "body": leaders.body, "cta": leaders.cta}


def _change(c: CopyChange) -> dict[str, Any]:
    return {"part": c.slot, "text": c.text, "cta": c.cta, "sends": c.sends, "clicks": c.clicks, "by": c.by}


def _sent(detail: "StartResult", approach: Approach, segment: Segment) -> list[Any]:
    return [s for j in detail.journeys[approach] for s in j.stays if s.segment is segment and s.email is EmailFate.SENT]


def _tally(stays: list[Any]) -> dict[str, Any]:
    sends, clicks, goals = len(stays), sum(s.clicked for s in stays), sum(s.left is not None for s in stays)
    return {"sends": sends, "clicks": clicks, "goal_actions": goals, "click_rate": clicks / sends if sends else None, "goal_rate": goals / sends if sends else None}


def _against(yours: dict[str, Any], tally: dict[str, Any]) -> dict[str, Any]:
    """A version's rates minus your email's, in points: how much better or worse it did."""
    return {
        f"{rate}_vs_yours": (tally[rate] - yours[rate]) * 100 if tally[rate] is not None and yours[rate] is not None else None
        for rate in ("click_rate", "goal_rate")
    }


def _versions(detail: "StartResult", segment: Segment, offer_labels_: dict[Offer, str]) -> dict[str, Any]:
    """Every version of this segment's email in the first replay, and how it did against yours: your email
    (the hand-written approach), each subject and body the AI loop tried (when it was written and dropped,
    and by whom), and for Trialists each offer. Goal rate counts the emailed merchants who went on to the
    segment's goal action."""
    yours = _tally(_sent(detail, Approach.HAND_WRITTEN, segment))
    ai_sent = _sent(detail, Approach.AI_LOOP, segment)
    loop = detail.loop
    versions: list[dict[str, Any]] = []
    if segment is Segment.IDLE:
        for v in loop.versions:
            tally = _tally([s for s in ai_sent if s.version == v.number])
            versions.append({
                "part": f"v{v.number}" + (f" · new {v.changed}" if v.changed else " · your email"), "text": f"{v.subject} / {v.body}", "cta": v.cta,
                "by": v.by, "status": {"champion": "leading", "challenger": "in play"}.get(v.status, "dropped"),
                "written_week": week_of(v.introduced_day), "dropped_week": week_of(v.sunset_day) if v.sunset_day is not None else None,
                "number": v.number, "hypothesis": v.hypothesis, **tally, **_against(yours, tally),
            })
    else:
        own = loop.segment_versions[segment]
        for sv, after in zip(own, [*own[1:], None]):
            tally = _tally([s for s in ai_sent if s.version == sv.number])
            versions.append({
                "part": f"v{sv.number}" + (f" · borrowed {sv.changed}" if sv.changed else " · your email"), "text": f"{sv.subject} / {sv.body}", "cta": sv.cta,
                "by": "you" if sv.borrowed_from_test is None else f"borrowed from Idle test {sv.borrowed_from_test} (v{sv.idle_version})",
                "status": "leading" if after is None else "dropped", "written_week": week_of(sv.day), "dropped_week": week_of(after.day) if after is not None else None,
                "number": sv.number, "hypothesis": sv.hypothesis, **tally, **_against(yours, tally),
            })
    offers = []
    if segment is Segment.TRIALIST:
        for offer in Offer:
            tally = _tally([s for s in ai_sent if s.offer is offer])
            offers.append({"offer": offer.value, "label": offer_labels_[offer], **tally, **_against(yours, tally)})
    return {"yours": yours, "ai": versions, "offers": offers, "ai_overall": {**_tally(ai_sent), **_against(yours, _tally(ai_sent))}}
