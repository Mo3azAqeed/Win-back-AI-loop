"""What every test file shares: the settings, a ready-made run, and ways to change a setting for one test."""

import dataclasses
from pathlib import Path

import pytest

from winback import RunResult, Segment, Settings, load_settings, run_simulation

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings.toml"
# The settings file and the files load_settings reads beside it.
SETTINGS_FILES = ("settings.toml", "first_drafts.toml", "prewritten.toml", "fact_sheet.toml")


@pytest.fixture(scope="session")
def run() -> RunResult:
    """One replay of the bundled settings from seed 1. Shared by every test that only reads it."""
    return run_simulation(load_settings(SETTINGS), seed=1)


def copy_settings(folder: Path) -> Path:
    """Copy the settings and the files beside them into a folder, so a test can change the copy; returns the settings file."""
    for name in SETTINGS_FILES:
        (folder / name).write_text((ROOT / name).read_text())
    return folder / "settings.toml"


def only(settings: Settings, *starts: int) -> Settings:
    """The same settings, run only from these starting numbers of merchants."""
    return dataclasses.replace(settings, start_sizes=starts)


def with_segment(settings: Settings, segment: Segment, **changes: float) -> Settings:
    """The same settings with one segment's hidden truth changed."""
    return dataclasses.replace(settings, segments={**settings.segments, segment: dataclasses.replace(settings.segments[segment], **changes)})
