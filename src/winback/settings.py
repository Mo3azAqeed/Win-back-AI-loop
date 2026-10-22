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
class Settings:
    start_sizes: tuple[int, ...]
    already_paying_share: float
    weeks: int
    growth_first_week: float
    growth_last_week: float
    run_out_days: int
    idle_judge_days: float
    idle_first_draft_after_days: float
    idle_organic_share: float
    idle_organic_mean_days: float
    idle_read_rate: float
    idle_click_rate: float
    idle_act_rate: float
    idle_response_mean_days: float
    first_drafts: dict[str, Email]
    entries: tuple[Setting, ...]


def load_settings(path: Path) -> Settings:
    """Load the settings file and the first drafts that sit next to it."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    with (path.parent / "first_drafts.toml").open("rb") as f:
        drafts = {segment: Email(d["subject"], d["body"], d["cta"]) for segment, d in tomllib.load(f).items()}
    entries = {s.key: s for s in _entries(raw)}
    return Settings(
        start_sizes=(int(entries["merchants.start"].value), int(entries["merchants.start_alternative"].value)),
        already_paying_share=entries["merchants.already_paying_share"].value,
        weeks=int(entries["growth.weeks"].value),
        growth_first_week=entries["growth.first_week"].value,
        growth_last_week=entries["growth.last_week"].value,
        run_out_days=int(entries["simulation.run_out_days"].value),
        idle_judge_days=entries["idle.judge_days"].value,
        idle_first_draft_after_days=entries["idle.first_draft_after_days"].value,
        idle_organic_share=entries["idle.organic_share"].value,
        idle_organic_mean_days=entries["idle.organic_mean_days"].value,
        idle_read_rate=entries["idle.read_rate"].value,
        idle_click_rate=entries["idle.click_rate"].value,
        idle_act_rate=entries["idle.act_rate"].value,
        idle_response_mean_days=entries["idle.response_mean_days"].value,
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
