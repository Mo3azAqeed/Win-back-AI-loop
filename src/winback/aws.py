"""The Lambda adapter: run the simulation on AWS and keep the report in S3."""

import dataclasses
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import boto3

from winback.copywriter import Copywriter, openrouter, plumbing
from winback.export import run_data
from winback.run import run_simulation
from winback.segments import Segment
from winback.settings import Email, Settings, load_settings

LATEST = "latest.md"
# The send times you can pick for your email: the timings the AI loop tests too.
SEND_AFTER = {"1 hour": 1 / 24, "2 days": 2.0, "5 days": 5.0}
LIMITS = {"subject": 200, "body": 3000, "cta": 60}
# The Lambda package holds the winback folder with the settings files beside it.
BUNDLED_SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"


def handler(event: Mapping[str, object], context: object) -> dict[str, str]:
    """Lambda entry point. The bucket and alert topic come from the environment the SAM template sets."""
    bucket, topic, region = os.environ["REPORTS_BUCKET"], os.environ["ALERTS_TOPIC_ARN"], os.environ["AWS_REGION"]
    s3 = boto3.client("s3")

    def put(key: str, text: str) -> None:
        kind = "application/json" if key.endswith(".json") else "text/markdown; charset=utf-8"
        s3.put_object(Bucket=bucket, Key=key, Body=text.encode(), ContentType=kind)

    def openrouter_key() -> str:
        name = os.environ["OPENROUTER_KEY_PARAMETER"]
        try:
            value: str = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
        except Exception as error:
            raise RuntimeError(f"Can't read the OpenRouter key from Parameter Store ({name}): create it as a SecureString (docs/aws-setup.md).") from error
        return value

    if event.get("plumbing"):
        return {"plumbing": "\n".join(plumbing(load_settings(BUNDLED_SETTINGS), openrouter_key()))}
    key = run_and_save(event, today=datetime.now(UTC).date(), settings_path=BUNDLED_SETTINGS, put=put, openrouter_key=openrouter_key)
    boto3.client("sns").publish(TopicArn=topic, Subject="Win-back report ready", Message=ready_message(bucket, region, key))
    return {"report": f"s3://{bucket}/{key}"}


def run_and_save(
    event: Mapping[str, object], *, today: date, settings_path: Path, put: Callable[[str, str], None], openrouter_key: Callable[[], str] | None = None
) -> str:
    """Run the simulation the event asks for, put its report under its own key and as the latest, its data
    for the web app beside it, and a line in the run list; return the report's key.

    The event may hold a seed, one starting size and a number of replays. Without a seed the date is used, so
    weekly runs differ; without a number of replays the settings decide (200). "writer": "ai" has the real
    writer and judge write the AI loop's words, with the key openrouter_key reads; otherwise the stand-in does."""
    seed = _whole_number(event, "seed")
    if seed is None:
        seed = int(today.strftime("%Y%m%d"))
    start = _whole_number(event, "start")
    replays = _whole_number(event, "replays")
    settings = load_settings(settings_path)
    if event.get("emails") is not None:
        settings = with_your_emails(settings, checked_emails(event["emails"]))
    if start is not None:
        settings = dataclasses.replace(settings, start_sizes=(start,))
    name = run_name(today, seed, start)
    copywriter: Copywriter | None = None
    if checked_writer(event.get("writer")) == "ai":
        if openrouter_key is None:
            raise ValueError("The AI writer needs the OpenRouter key")
        copywriter = openrouter(settings, openrouter_key())
    result = run_simulation(settings, seed, replays, copywriter)
    data = run_data(settings, result, seed=seed, created=today)
    data["writer"] = copywriter.name if copywriter is not None else "stand-in writer"
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
    return {"run": name, "created": data["created"], "seed": data["seed"], "replays": data["replays"], "writer": data.get("writer"), "headline": headline}


def checked_writer(raw: object) -> str:
    """Who writes the AI loop's words: "stand-in" (the default) or "ai" (the real writer and judge)."""
    if raw is None or raw == "stand-in":
        return "stand-in"
    if raw == "ai":
        return "ai"
    raise ValueError(f'writer must be "stand-in" or "ai", got {raw!r}')


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


def checked_emails(raw: object) -> list[dict[str, str]]:
    """Your hand-written emails as the app sends them: one per stage, with a subject, body, button text and
    one of the send times the simulation tests. Raises ValueError for anything it can't simulate."""
    if not isinstance(raw, list) or not all(isinstance(e, dict) for e in raw) or len(raw) != len(Segment) or {e.get("segment") for e in raw} != {s.value for s in Segment}:
        raise ValueError("Send one email for each stage: idle, drafter and trialist.")
    for email in raw:
        for field, limit in LIMITS.items():
            value = email.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f"Each email needs a {field} of 1 to {limit} characters.")
        if email.get("send_after") not in SEND_AFTER:
            raise ValueError(f"Send after must be one of: {', '.join(SEND_AFTER)}.")
    return [{key: email[key] for key in ("segment", "subject", "body", "cta", "send_after")} for email in raw]


def with_your_emails(settings: Settings, emails: list[dict[str, str]]) -> Settings:
    """The settings with your emails as the first drafts: what the hand-written approach sends, when, and
    where the AI loop starts."""
    drafts = dict(settings.first_drafts)
    segments = dict(settings.segments)
    for email in emails:
        segment = Segment(email["segment"])
        drafts[segment.value] = Email(email["subject"], email["body"], email["cta"])
        segments[segment] = dataclasses.replace(segments[segment], hand_written_after_days=SEND_AFTER[email["send_after"]])
    return dataclasses.replace(settings, first_drafts=drafts, segments=segments)