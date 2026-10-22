"""The Lambda adapter: run the simulation on AWS and keep the report in S3."""

import dataclasses
import os
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import boto3

from winback.run import run_simulation
from winback.settings import load_settings

LATEST = "latest.md"
# The Lambda package holds the winback folder with the settings files beside it.
BUNDLED_SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"


def handler(event: Mapping[str, object], context: object) -> dict[str, str]:
    """Lambda entry point. The bucket and alert topic come from the environment the SAM template sets."""
    bucket, topic, region = os.environ["REPORTS_BUCKET"], os.environ["ALERTS_TOPIC_ARN"], os.environ["AWS_REGION"]
    s3 = boto3.client("s3")

    def put(key: str, text: str) -> None:
        s3.put_object(Bucket=bucket, Key=key, Body=text.encode(), ContentType="text/markdown; charset=utf-8")

    key = publish(event, today=datetime.now(UTC).date(), settings_path=BUNDLED_SETTINGS, put=put)
    boto3.client("sns").publish(TopicArn=topic, Subject="Win-back report ready", Message=ready_message(bucket, region, key))
    return {"report": f"s3://{bucket}/{key}"}


def publish(event: Mapping[str, object], *, today: date, settings_path: Path, put: Callable[[str, str], None]) -> str:
    """Run the simulation the event asks for, put its report under its own key and as the latest, and return its key.

    The event may hold a seed and one starting size. Without a seed the date is used, so weekly runs differ."""
    seed = _whole_number(event, "seed")
    if seed is None:
        seed = int(today.strftime("%Y%m%d"))
    start = _whole_number(event, "start")
    settings = load_settings(settings_path)
    key = f"runs/{today.isoformat()}-seed{seed}.md"
    if start is not None:
        settings = dataclasses.replace(settings, start_sizes=(start,))
        key = f"runs/{today.isoformat()}-seed{seed}-start{start}.md"
    report = run_simulation(settings, seed).report
    put(key, report)
    put(LATEST, report)
    return key


def _whole_number(event: Mapping[str, object], name: str) -> int | None:
    value = event.get(name)
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise ValueError(f"{name} must be a whole number, got {value!r}")


def ready_message(bucket: str, region: str, key: str) -> str:
    """The "report ready" email: where the new report is, and where the latest one always is."""
    console = f"https://s3.console.aws.amazon.com/s3/object/{bucket}?region={region}&prefix="
    return (
        "A new win-back simulation report is ready.\n\n"
        f"This run:   {console}{key}\n"
        f"Latest run: {console}{LATEST}\n"
    )
