"""Loading the settings file, where every number is marked as real or placeholder."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from winback.segments import Segment
from winback.trialist import Offer


@dataclass(frozen=True)
class Setting:
    key: str
    value: float
    placeholder: bool
    note: str


@dataclass(frozen=True)
class Email:
    subject: str
    body: str
    cta: str


@dataclass(frozen=True)
class Variant:
    """A prewritten subject (cta empty) or body for the stand-in writer, the hypothesis behind it, and its
    hidden quality for Idle merchants: 100 is your first draft. Follow-through is hidden too: how likely a
    merchant who clicks is to act, where 100 is your first draft (an email can win clicks it doesn't keep)."""

    text: str
    cta: str
    quality: float
    placeholder: bool
    hypothesis: str = ""
    follow_through: float = 100.0


@dataclass(frozen=True)
class SegmentSettings:
    """How merchants in one segment behave. The read and click rates are your first draft's
    for that segment (hidden quality 100). The horizon is the fixed number of days from the trigger
    over which true lift is counted."""

    horizon_days: float
    miss_window_days: float
    hand_written_after_days: float
    organic_share: float
    organic_mean_days: float
    read_rate: float
    click_rate: float
    act_rate: float
    response_mean_days: float
    read_shift_1_hour: float
    read_shift_5_days: float


@dataclass(frozen=True)
class LoopSettings:
    """How the AI loop tests a challenger against the champion in Idle, and when a test ends."""

    min_sends: int  # each version's sends in a test before a verdict on clicks
    verdict_confidence: float  # how sure a verdict must be, 0 to 1
    same_margin: float  # click rates closer than this (a share: 0.01 is 1 point) count as the same
    test_max_weeks: int
    test_max_sends: int  # per version
    challenger_share: float  # the share of Idle emails the challenger gets while a test runs
    keep_ahead_at_limit: bool  # at the limit, the version ahead on clicks stays, rather than always the champion
    carry_over: float  # the share of the Idle leader's edge that Drafter and Trialist emails get, 0 to 1


@dataclass(frozen=True)
class OfferSettings:
    """What each Trialist offer gives, the line it adds to the Trialist first draft (from the fact sheet), and
    (hidden truth) how much more likely it makes a Trialist who clicks to pay."""

    extra_trial_days: float
    discount_price_share: float  # the share of the first month's price a Trialist pays with the discount
    pay_lift: dict[Offer, float]  # 0.3 means 30% more likely to pay after clicking
    lines: dict[Offer, str]  # empty for no offer


@dataclass(frozen=True)
class Settings:
    start_sizes: tuple[int, ...]
    already_paying_share: float
    existing_shares: dict[Segment, float]
    existing_spread_days: float
    weeks: int
    growth_first_week: float
    growth_last_week: float
    holdout_share: float
    min_gap_days: float
    trial_days: float
    monthly_price: float
    paid_window_days: float
    segments: dict[Segment, SegmentSettings]
    first_drafts: dict[str, Email]
    prewritten_subjects: tuple[Variant, ...]
    prewritten_bodies: tuple[Variant, ...]
    loop: LoopSettings
    offers: OfferSettings
    replays: int
    entries: tuple[Setting, ...]


def load_settings(path: Path) -> Settings:
    """Load the settings file, and the first drafts, the stand-in writer's list and the fact sheet that sit next to it."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    with (path.parent / "first_drafts.toml").open("rb") as f:
        raw_drafts = tomllib.load(f)
    drafts = {segment: Email(d["subject"], d["body"], d["cta"]) for segment, d in raw_drafts.items()}
    with (path.parent / "prewritten.toml").open("rb") as f:
        prewritten = tomllib.load(f)
    with (path.parent / "fact_sheet.toml").open("rb") as f:
        offer_lines = tomllib.load(f)["offers"]
    entries = {s.key: s for s in _entries(raw)}

    def value(key: str) -> float:
        return entries[key].value

    def segment(name: str) -> SegmentSettings:
        return SegmentSettings(**{field: value(f"{name}.{field}") for field in SegmentSettings.__dataclass_fields__})

    return Settings(
        start_sizes=(int(value("merchants.start")), int(value("merchants.start_alternative"))),
        already_paying_share=value("merchants.already_paying_share"),
        existing_shares={s: value(f"merchants.existing_{s.value}_share") for s in Segment},
        existing_spread_days=value("merchants.existing_spread_days"),
        weeks=int(value("growth.weeks")),
        growth_first_week=value("growth.first_week"),
        growth_last_week=value("growth.last_week"),
        holdout_share=value("holdout.share"),
        min_gap_days=value("sending.min_gap_days"),
        trial_days=value("trial.days"),
        monthly_price=value("paid.monthly_price"),
        paid_window_days=value("paid.window_days"),
        segments={s: segment(s.value) for s in Segment},
        first_drafts=drafts,
        prewritten_subjects=tuple(_variant(v, "subject") for v in prewritten["subject"]),
        prewritten_bodies=tuple(_variant(v, "body") for v in prewritten["body"]),
        loop=LoopSettings(
            min_sends=int(value("ai_loop.min_sends")),
            verdict_confidence=value("ai_loop.verdict_confidence"),
            same_margin=value("ai_loop.same_margin_points") / 100,
            test_max_weeks=int(value("ai_loop.test_max_weeks")),
            test_max_sends=int(value("ai_loop.test_max_sends")),
            challenger_share=value("ai_loop.challenger_share"),
            keep_ahead_at_limit=value("ai_loop.keep_ahead_at_limit") == 1,
            carry_over=value("ai_loop.carry_over"),
        ),
        offers=OfferSettings(
            extra_trial_days=value("offers.extra_trial_days"),
            discount_price_share=value("offers.discount_price_share"),
            pay_lift={Offer.NONE: 0.0, Offer.EXTENSION: value("offers.extension_pay_lift"), Offer.DISCOUNT: value("offers.discount_pay_lift")},
            lines={Offer.NONE: "", Offer.EXTENSION: offer_lines["extension"], Offer.DISCOUNT: offer_lines["discount"]},
        ),
        replays=int(value("replays.count")),
        entries=tuple(entries.values()),
    )


def _variant(raw: dict[str, Any], slot: str) -> Variant:
    """One prewritten subject or body; its hidden quality is a number like any setting, marked as real or placeholder."""
    [quality] = _entries({"quality": raw["quality"]}, f"prewritten.{slot}.")
    return Variant(raw["text"], raw.get("cta", ""), quality.value, quality.placeholder, raw.get("hypothesis", ""))


def _entries(raw: dict[str, Any], prefix: str = "") -> list[Setting]:
    out: list[Setting] = []
    for name, item in raw.items():
        key = f"{prefix}{name}"
        if isinstance(item, dict) and "value" in item:
            out.append(Setting(key, float(item["value"]), bool(item["placeholder"]), str(item.get("note", ""))))
        elif isinstance(item, dict):
            out.extend(_entries(item, key + "."))
        else:
            raise ValueError(f"Setting {key} must be written as {{ value = ..., placeholder = ... }}")
    return out
