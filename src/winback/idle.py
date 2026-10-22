"""Idle merchants: signed up, no draft yet. Goal action: start a draft."""

import math
from dataclasses import dataclass

from winback.draws import draw
from winback.settings import Settings
from winback.world import Merchant

APPROACHES = ("no_email", "hand_written")
APPROACH_LABEL = {"no_email": "No email", "hand_written": "Hand-written email (your first draft)"}


@dataclass(frozen=True)
class SegmentOutcome:
    judged: int
    reached: int
    sent: int
    skipped: int
    true_lift: float

    @property
    def share(self) -> float:
        return self.reached / self.judged if self.judged else 0.0


def _after(seed: int, key: str, purpose: str, mean_days: float) -> float:
    """A seeded waiting time in days with the given average."""
    return -mean_days * math.log(1.0 - draw(seed, key, "idle", purpose))


def _draft_day(settings: Settings, m: Merchant, seed: int, emailed: bool, end: float) -> tuple[float | None, str]:
    """When the merchant starts a draft (None if never), and what happened to its email:
    'none' (no email planned), 'sent', or 'skipped' (it started a draft before the email was due)."""
    drafted: float | None = None
    if draw(seed, m.key, "idle", "organic") < settings.idle_organic_share:
        drafted = m.arrival_day + _after(seed, m.key, "organic_time", settings.idle_organic_mean_days)
    if not emailed:
        return drafted, "none"
    send = m.arrival_day + settings.idle_first_draft_after_days
    if drafted is not None and drafted < send:
        return drafted, "skipped"
    if send > end:
        return drafted, "none"
    read = draw(seed, m.key, "idle", "read") < settings.idle_read_rate
    clicked = read and draw(seed, m.key, "idle", "click") < settings.idle_click_rate
    if clicked and draw(seed, m.key, "idle", "act") < settings.idle_act_rate:
        prompted = send + _after(seed, m.key, "response", settings.idle_response_mean_days)
        drafted = prompted if drafted is None else min(drafted, prompted)
    return drafted, "sent"


def idle_outcomes(settings: Settings, merchants: list[Merchant], seed: int) -> dict[str, SegmentOutcome]:
    """Score each approach on the same new signups with the same luck."""
    end = settings.weeks * 7 + settings.run_out_days
    counts: dict[str, list[int]] = {}
    for approach in APPROACHES:
        judged = reached = sent = skipped = 0
        for m in merchants:
            if m.existing or m.arrival_day + settings.idle_judge_days > end:
                continue
            drafted, email = _draft_day(settings, m, seed, approach == "hand_written", end)
            judged += 1
            reached += drafted is not None and drafted <= m.arrival_day + settings.idle_judge_days
            sent += email == "sent"
            skipped += email == "skipped"
        counts[approach] = [judged, reached, sent, skipped]
    base = counts["no_email"][1] / counts["no_email"][0] if counts["no_email"][0] else 0.0
    return {
        a: SegmentOutcome(j, r, s, k, (r / j if j else 0.0) - base)
        for a, (j, r, s, k) in counts.items()
    }
