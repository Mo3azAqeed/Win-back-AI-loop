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
class SegmentSettings:
    """How merchants in one segment behave. The read and click rates are your first draft's
    for that segment (hidden quality 100)."""

    hand_written_after_days: float
    organic_share: float
    organic_mean_days: float
    read_rate: float
    click_rate: float
    act_rate: float
    response_mean_days: float


@dataclass(frozen=True)
class Settings:
    start_sizes: tuple[int, ...]
    already_paying_share: float
    existing_shares: dict[Segment, float]
    existing_spread_days: float
    weeks: int
    growth_first_week: float
    growth_last_week: float
    run_out_days: int
    min_gap_days: float
    trial_days: float
    idle_horizon_days: float
    segments: dict[Segment, SegmentSettings]
    first_drafts: dict[str, Email]
    entries: tuple[Setting, ...]


def load_settings(path: Path) -> Settings:
    """Load the settings file and the first drafts that sit next to it."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    with (path.parent / "first_drafts.toml").open("rb") as f:
        drafts = {segment: Email(d["subject"], d["body"], d["cta"]) for segment, d in tomllib.load(f).items()}
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
        run_out_days=int(value("simulation.run_out_days")),
        min_gap_days=value("sending.min_gap_days"),
        trial_days=value("trial.days"),
        idle_horizon_days=value("idle.horizon_days"),
        segments={s: segment(s.value) for s in Segment},
        first_drafts=drafts,
        entries=tuple(entries.values()),
    )


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
