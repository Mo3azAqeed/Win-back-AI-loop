import dataclasses
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from winback import load_settings, run_simulation
from winback.aws import publish, ready_message

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings.toml"
TODAY = date(2026, 10, 22)


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def put(self, key: str, text: str) -> None:
        self.objects[key] = text


def test_a_run_puts_the_same_report_the_simulation_returns() -> None:
    bucket = FakeBucket()

    key = publish({"seed": 7}, today=TODAY, settings_path=SETTINGS, put=bucket.put)

    report = run_simulation(load_settings(SETTINGS), seed=7).report
    assert key == "runs/2026-10-22-seed7.md"
    assert bucket.objects == {key: report, "latest.md": report}


def test_a_scheduled_run_without_a_seed_uses_the_date_so_each_week_differs() -> None:
    bucket = FakeBucket()

    key = publish({}, today=TODAY, settings_path=SETTINGS, put=bucket.put)

    assert key == "runs/2026-10-22-seed20261022.md"
    assert bucket.objects[key] == run_simulation(load_settings(SETTINGS), seed=20261022).report


def test_a_run_can_ask_for_one_starting_size_only() -> None:
    bucket = FakeBucket()

    key = publish({"seed": 7, "start": 1000}, today=TODAY, settings_path=SETTINGS, put=bucket.put)

    only_1000 = dataclasses.replace(load_settings(SETTINGS), start_sizes=(1000,))
    assert key == "runs/2026-10-22-seed7-start1000.md"
    assert bucket.objects[key] == run_simulation(only_1000, seed=7).report


@pytest.mark.parametrize("event", [{"seed": "7"}, {"seed": 7.5}, {"seed": True}, {"start": "1000"}])
def test_a_run_refuses_a_seed_or_start_that_is_not_a_whole_number(event: dict[str, object]) -> None:
    bucket = FakeBucket()

    with pytest.raises(ValueError, match="must be a whole number"):
        publish(event, today=TODAY, settings_path=SETTINGS, put=bucket.put)

    assert bucket.objects == {}


def test_the_report_ready_email_links_to_this_run_and_to_the_latest() -> None:
    message = ready_message("winback-reports", "eu-west-1", "runs/2026-10-22-seed7.md")

    assert "https://s3.console.aws.amazon.com/s3/object/winback-reports?region=eu-west-1&prefix=runs/2026-10-22-seed7.md" in message
    assert "prefix=latest.md" in message


def test_the_lambda_package_finds_its_bundled_settings(tmp_path: Path) -> None:
    # Build the package exactly as `sam build` does, then run it from there, away from the repo.
    package = tmp_path / "package"
    subprocess.run(["make", "-s", "build-SimulationFunction", f"ARTIFACTS_DIR={package}"], cwd=ROOT, check=True)
    script = (
        "from datetime import date\n"
        "from winback.aws import BUNDLED_SETTINGS, publish\n"
        "put = lambda key, text: print(key) if key != 'latest.md' else None\n"
        "publish({'seed': 7}, today=date(2026, 10, 22), settings_path=BUNDLED_SETTINGS, put=put)\n"
    )

    ran = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env={"PYTHONPATH": str(package)}, capture_output=True, text=True)

    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "runs/2026-10-22-seed7.md\n"
