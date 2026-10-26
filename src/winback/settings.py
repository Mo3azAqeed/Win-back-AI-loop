"""Loading the settings file, where every number is marked as real or placeholder."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from winback.segments import Segment


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
    """A prewritten subject (cta empty) or body for the stand-in writer, with its hidden quality
    for Idle merchants: 100 is your first draft."""

    text: str
    cta: str
    quality: float
    placeholder: bool


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
    """How the AI loop tests and retires subjects and bodies."""

    active_variants: int
    min_sends: int
    retire_confidence: float
    prior_sends: float
    carry_over: float  # the share of the Idle leader's edge that Drafter and Trialist emails get, 0 to 1


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
    entries: tuple[Setting, ...]


def load_settings(path: Path) -> Settings:
    """Load the settings file, and the first drafts and the stand-in writer's list that sit next to it."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    with (path.parent / "first_drafts.toml").open("rb") as f:
        drafts = {segment: Email(d["subject"], d["body"], d["cta"]) for segment, d in tomllib.load(f).items()}
    with (path.parent / "prewritten.toml").open("rb") as f:
        prewritten = tomllib.load(f)
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
            active_variants=int(value("ai_loop.active_variants")),
            min_sends=int(value("ai_loop.min_sends")),
            retire_confidence=value("ai_loop.retire_confidence"),
            prior_sends=value("ai_loop.prior_sends"),
            carry_over=value("ai_loop.carry_over"),
        ),
        entries=tuple(entries.values()),
    )


def _variant(raw: dict[str, Any], slot: str) -> Variant:
    """One prewritten subject or body; its hidden quality is a number like any setting, marked as real or placeholder."""
    [quality] = _entries({"quality": raw["quality"]}, f"prewritten.{slot}.")
    return Variant(raw["text"], raw.get("cta", ""), quality.value, quality.placeholder)


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
