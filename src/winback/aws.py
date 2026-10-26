"""The Lambda adapter: run the simulation on AWS and keep the report in S3."""

import dataclasses
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import boto3

from winback.export import run_data
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
        kind = "application/json" if key.endswith(".json") else "text/markdown; charset=utf-8"
        s3.put_object(Bucket=bucket, Key=key, Body=text.encode(), ContentType=kind)

    key = run_and_save(event, today=datetime.now(UTC).date(), settings_path=BUNDLED_SETTINGS, put=put)
    boto3.client("sns").publish(TopicArn=topic, Subject="Win-back report ready", Message=ready_message(bucket, region, key))
    return {"report": f"s3://{bucket}/{key}"}


def run_and_save(event: Mapping[str, object], *, today: date, settings_path: Path, put: Callable[[str, str], None]) -> str:
    """Run the simulation the event asks for, put its report under its own key and as the latest, its data
    for the web app beside it, and a line in the run list; return the report's key.

    The event may hold a seed, one starting size and a number of replays. Without a seed the date is used, so
    weekly runs differ; without a number of replays the settings decide (200)."""
    seed = _whole_number(event, "seed")
    if seed is None:
        seed = int(today.strftime("%Y%m%d"))
    start = _whole_number(event, "start")
    replays = _whole_number(event, "replays")
    settings = load_settings(settings_path)
    if start is not None:
        settings = dataclasses.replace(settings, start_sizes=(start,))
    name = run_name(today, seed, start)
    result = run_simulation(settings, seed, replays if replays is not None else settings.replays)
    data = run_data(settings, result, seed=seed, created=today)
    put(f"runs/{name}.md", result.report)
    put(f"runs/{name}.json", json.dumps(data))
    put(f"index/{name}.json", json.dumps(_index_entry(name, data)))
    put(LATEST, result.report)
    return f"runs/{name}.md"


def run_name(today: date, seed: int, start: int | None) -> str:
    """A run's name: its date, its seed, and its one starting size if it had only one."""
    return f"{today.isoformat()}-seed{seed}" + (f"-start{start}" if start is not None else "")


def _index_entry(name: str, data: dict[str, object]) -> dict[str, object]:
    """A run's line in the web app's run list: when, which seed, how many replays, and the headline."""
    starts = data["starts"]
    assert isinstance(starts, list)
    headline = [
        {
            "merchants": s["merchants"],
            "segments": [
                {
                    "label": seg["label"],
                    "ai": next(a["average"] for a in seg["approaches"] if a["approach"] == "ai_loop"),
                    "hand": next(a["average"] for a in seg["approaches"] if a["approach"] == "hand_written"),
                    "ai_did_better": seg["ai_did_better"],
                }
                for seg in s["segments"]
            ],
        }
        for s in starts
    ]
    return {"run": name, "created": data["created"], "seed": data["seed"], "replays": data["replays"], "headline": headline}


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
