import dataclasses
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from winback import load_settings, run_simulation
from winback import aws
from winback.aws import ready_message, run_and_save

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

    key = run_and_save({"seed": 7, "replays": 2}, today=TODAY, settings_path=SETTINGS, put=bucket.put)

    report = run_simulation(load_settings(SETTINGS), seed=7, replays=2).report
    assert key == "runs/2026-10-22-seed7.md"
    assert {k: v for k, v in bucket.objects.items() if k.endswith(".md")} == {key: report, "latest.md": report}


def test_a_scheduled_run_without_a_seed_uses_the_date_so_each_week_differs() -> None:
    bucket = FakeBucket()

    key = run_and_save({"replays": 1}, today=TODAY, settings_path=SETTINGS, put=bucket.put)

    assert key == "runs/2026-10-22-seed20261022.md"
    assert bucket.objects[key] == run_simulation(load_settings(SETTINGS), seed=20261022).report


def test_a_run_can_ask_for_one_starting_size_only() -> None:
    bucket = FakeBucket()

    key = run_and_save({"seed": 7, "start": 1000, "replays": 1}, today=TODAY, settings_path=SETTINGS, put=bucket.put)

    only_1000 = dataclasses.replace(load_settings(SETTINGS), start_sizes=(1000,))
    assert key == "runs/2026-10-22-seed7-start1000.md"
    assert bucket.objects[key] == run_simulation(only_1000, seed=7).report


def test_without_a_number_of_replays_a_run_replays_as_many_times_as_the_settings_say(tmp_path: Path) -> None:
    for name in ("settings.toml", "first_drafts.toml", "prewritten.toml"):
        (tmp_path / name).write_text((ROOT / name).read_text())
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(settings_file.read_text().replace("count = { value = 200,", "count = { value = 2,"))
    bucket = FakeBucket()

    key = run_and_save({"seed": 7, "start": 1000}, today=TODAY, settings_path=settings_file, put=bucket.put)

    assert load_settings(settings_file).replays == 2
    assert "## Across 2 replays" in bucket.objects[key]


@pytest.mark.parametrize("event", [{"seed": "7"}, {"seed": 7.5}, {"seed": True}, {"start": "1000"}, {"replays": "2"}])
def test_a_run_refuses_a_seed_start_or_number_of_replays_that_is_not_a_whole_number(event: dict[str, object]) -> None:
    bucket = FakeBucket()

    with pytest.raises(ValueError, match="must be a whole number"):
        run_and_save(event, today=TODAY, settings_path=SETTINGS, put=bucket.put)

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
        "from winback.aws import BUNDLED_SETTINGS, run_and_save\n"
        "put = lambda key, text: print(key) if key != 'latest.md' else None\n"
        "run_and_save({'seed': 7, 'replays': 1}, today=date(2026, 10, 22), settings_path=BUNDLED_SETTINGS, put=put)\n"
    )

    ran = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env={"PYTHONPATH": str(package)}, capture_output=True, text=True)

    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "runs/2026-10-22-seed7.md\nruns/2026-10-22-seed7.json\nindex/2026-10-22-seed7.json\n"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def put_object(self, **kwargs: object) -> None:
        self.calls.append(("put_object", kwargs))

    def publish(self, **kwargs: object) -> None:
        self.calls.append(("publish", kwargs))


def test_the_lambda_handler_saves_to_the_bucket_and_emails_the_alerts_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    clients = {"s3": FakeClient(), "sns": FakeClient()}
    monkeypatch.setattr("boto3.client", lambda name: clients[name])
    monkeypatch.setattr(aws, "BUNDLED_SETTINGS", SETTINGS)
    monkeypatch.setenv("REPORTS_BUCKET", "winback-reports")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:eu-west-1:123456789012:winback-alerts")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    result = aws.handler({"seed": 7, "replays": 1}, None)

    report = run_simulation(load_settings(SETTINGS), seed=7).report
    key = result["report"].removeprefix("s3://winback-reports/")
    saved = [(c["Key"], c["ContentType"]) for _, c in clients["s3"].calls]
    assert saved == [
        (key, "text/markdown; charset=utf-8"),
        (key.replace(".md", ".json"), "application/json"),
        (key.replace("runs/", "index/").replace(".md", ".json"), "application/json"),
        ("latest.md", "text/markdown; charset=utf-8"),
    ]
    assert [c["Body"] for _, c in clients["s3"].calls if str(c["Key"]).endswith(".md")] == [report.encode(), report.encode()]
    [(_, email)] = clients["sns"].calls
    assert email["TopicArn"] == "arn:aws:sns:eu-west-1:123456789012:winback-alerts"
    assert email["Message"] == ready_message("winback-reports", "eu-west-1", key)
