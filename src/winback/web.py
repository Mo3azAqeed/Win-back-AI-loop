"""The web app: one page to start a simulation and see every run's results, served from a Lambda function URL.

Anyone with the link can look (every number is simulated); starting a run needs the access code kept in
Parameter Store, so nobody else can spend the account's Lambda time. Only one run goes at a time.
"""

import base64
import hmac
import json
import os
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import boto3

from winback.aws import run_name

PAGE = Path(__file__).resolve().parent / "web" / "index.html"
MAX_REPLAYS = 200
# A run that never reports back stops blocking new ones after this long; the simulation's own limit is 15 minutes.
RUN_GIVES_UP_AFTER = timedelta(minutes=20)
RUN_NAME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-seed[0-9]+(-start[0-9]+)?$")


class Store(Protocol):
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, text: str) -> None: ...
    def keys(self, prefix: str) -> list[str]: ...


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: str


def respond(
    method: str,
    path: str,
    body: bytes,
    *,
    store: Store,
    start_run: Callable[[dict[str, object]], None],
    access_code: str | None,
    today: date,
    now: datetime,
    new_seed: Callable[[], int],
) -> Response:
    """Answer one request to the app: the page, the run list, one run's data or report, or a new run."""
    if method == "GET" and path == "/":
        return Response(200, "text/html; charset=utf-8", PAGE.read_text())
    if method == "GET" and path == "/api/runs":
        return _json(200, {"runs": _finished(store), "running": _running(store, now)})
    parts = path.removeprefix("/api/runs/").split("/")
    if method == "GET" and path.startswith("/api/runs/") and RUN_NAME.match(parts[0]) and len(parts) <= 2:
        key = f"runs/{parts[0]}.json" if len(parts) == 1 else f"runs/{parts[0]}.md" if parts[1] == "report" else None
        text = store.get(key) if key else None
        if text is not None:
            return Response(200, "application/json" if key and key.endswith(".json") else "text/markdown; charset=utf-8", text)
    if method == "POST" and path == "/api/runs":
        return _start(body, store, start_run, access_code, today, now, new_seed)
    return _json(404, {"error": "Not found"})


def _start(
    body: bytes, store: Store, start_run: Callable[[dict[str, object]], None], access_code: str | None, today: date, now: datetime, new_seed: Callable[[], int]
) -> Response:
    if access_code is None:
        return _json(503, {"error": "Runs aren't switched on yet: create the access code in Parameter Store (docs/aws-setup.md)."})
    try:
        asked = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return _json(400, {"error": "Send JSON."})
    code = asked.get("code") if isinstance(asked, dict) else None
    if not isinstance(code, str) or not hmac.compare_digest(code.encode(), access_code.encode()):
        return _json(403, {"error": "Wrong access code."})
    replays = asked.get("replays")
    if not isinstance(replays, int) or isinstance(replays, bool) or not 1 <= replays <= MAX_REPLAYS:
        return _json(400, {"error": f"Ask for 1 to {MAX_REPLAYS} replays."})
    if _running(store, now):
        return _json(409, {"error": "A run is already going. Try again when it finishes."})
    seed = new_seed()
    name = run_name(today, seed, None)
    store.put(f"pending/{name}.json", json.dumps({"run": name, "requested": now.isoformat(), "replays": replays}))
    start_run({"seed": seed, "replays": replays})
    return _json(202, {"run": name})


def _finished(store: Store) -> list[dict[str, Any]]:
    """Every saved run's line, newest first."""
    entries = [json.loads(text) for key in store.keys("index/") if (text := store.get(key)) is not None]
    return sorted(entries, key=lambda e: (e["created"], e["run"]), reverse=True)


def _running(store: Store, now: datetime) -> list[dict[str, Any]]:
    """Runs asked for from the app that haven't saved their results yet and haven't been given up on."""
    done = {key.removeprefix("index/") for key in store.keys("index/")}
    running = []
    for key in store.keys("pending/"):
        text = store.get(key)
        if text is None or key.removeprefix("pending/") in done:
            continue
        entry = json.loads(text)
        if now - datetime.fromisoformat(entry["requested"]) < RUN_GIVES_UP_AFTER:
            running.append(entry)
    return running


def _json(status: int, content: object) -> Response:
    return Response(status, "application/json", json.dumps(content))


class NoSuchKey(Exception):
    """Raised by the S3 client when a key doesn't exist."""


class _S3Store:
    def __init__(self, bucket: str) -> None:
        self.bucket, self.s3 = bucket, boto3.client("s3")

    def get(self, key: str) -> str | None:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as error:  # botocore raises a generated NoSuchKey class per client
            if type(error).__name__ == "NoSuchKey":
                return None
            raise
        body: bytes = response["Body"].read()
        return body.decode()

    def put(self, key: str, text: str) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=text.encode(), ContentType="application/json")

    def keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        page = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        while True:
            keys += [item["Key"] for item in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                return keys
            page = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix, ContinuationToken=page["NextContinuationToken"])


def _access_code(name: str) -> str | None:
    try:
        value: str = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    except Exception as error:
        if type(error).__name__ == "ParameterNotFound":
            return None
        raise
    return value


def handler(event: Mapping[str, Any], context: object) -> dict[str, object]:
    """Lambda entry point for the function URL. The bucket, the simulation function and the access code's
    parameter name come from the environment the SAM template sets."""
    http = event["requestContext"]["http"]
    raw = event.get("body") or ""
    body = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()
    simulation = os.environ["SIMULATION_FUNCTION"]

    def start_run(payload: dict[str, object]) -> None:
        boto3.client("lambda").invoke(FunctionName=simulation, InvocationType="Event", Payload=json.dumps(payload))

    method = http["method"]
    try:
        response = respond(
            method,
            event["rawPath"],
            body,
            store=_S3Store(os.environ["REPORTS_BUCKET"]),
            start_run=start_run,
            access_code=_access_code(os.environ["ACCESS_CODE_PARAMETER"]) if method == "POST" else None,
            today=datetime.now(UTC).date(),
            now=datetime.now(UTC),
            new_seed=lambda: secrets.randbelow(10**9),
        )
    except Exception as error:
        if "AccessDenied" not in type(error).__name__ + str(error):
            raise
        # The permissions boundary caps what the app may do; an older boundary can't read reports yet.
        response = _json(500, {"error": "AWS refused access. Update the deploy role stack once more (docs/aws-setup.md, step 8)."})
    return {"statusCode": response.status, "headers": {"content-type": response.content_type, "cache-control": "no-store"}, "body": response.body}
