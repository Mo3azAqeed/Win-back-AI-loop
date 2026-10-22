"""Loading the settings file, where every number is marked as real or placeholder."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
class IdleSettings:
    """How Idle merchants behave. The read and click rates are your first draft's (hidden quality 100)."""

    horizon_days: float
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
    weeks: int
    growth_first_week: float
    growth_last_week: float
    run_out_days: int
    idle: IdleSettings
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

    return Settings(
        start_sizes=(int(value("merchants.start")), int(value("merchants.start_alternative"))),
        already_paying_share=value("merchants.already_paying_share"),
        weeks=int(value("growth.weeks")),
        growth_first_week=value("growth.first_week"),
        growth_last_week=value("growth.last_week"),
        run_out_days=int(value("simulation.run_out_days")),
        idle=IdleSettings(**{name: value(f"idle.{name}") for name in IdleSettings.__dataclass_fields__}),
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
