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
class Settings:
    start_sizes: tuple[int, ...]
    already_paying_share: float
    weeks: int
    growth_first_week: float
    growth_last_week: float
    entries: tuple[Setting, ...]


def load_settings(path: Path) -> Settings:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    entries = {s.key: s for s in _entries(raw)}
    return Settings(
        start_sizes=(int(entries["merchants.start"].value), int(entries["merchants.start_alternative"].value)),
        already_paying_share=entries["merchants.already_paying_share"].value,
        weeks=int(entries["growth.weeks"].value),
        growth_first_week=entries["growth.first_week"].value,
        growth_last_week=entries["growth.last_week"].value,
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
