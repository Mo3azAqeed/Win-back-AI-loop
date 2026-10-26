import base64
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from winback import Approach, Offer, Segment, load_settings, run_simulation
from winback import web
from winback.aws import run_and_save
from winback.export import run_data
from winback.web import respond

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "settings.toml"
TODAY = date(2026, 10, 26)
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.objects.get(key)

    def put(self, key: str, text: str) -> None:
        self.objects[key] = text

    def keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


@pytest.fixture(scope="module")
def saved() -> FakeBucket:
    bucket = FakeBucket()
    run_and_save({"seed": 7, "start": 1000, "replays": 3}, today=TODAY, settings_path=SETTINGS, put=bucket.put)
    return bucket


def call(bucket: FakeBucket, method: str, path: str, body: object = None, *, code: str | None = "letmein", now: datetime = NOW) -> tuple[int, Any, list[dict[str, object]]]:
    started: list[dict[str, object]] = []
    response = respond(
        method, path, json.dumps(body).encode() if body is not None else b"",
        store=bucket, start_run=started.append, access_code=code, today=TODAY, now=now, new_seed=lambda: 4242,
    )
    content = json.loads(response.body) if response.content_type == "application/json" else response.body
    return response.status, content, started


def test_each_run_saves_its_results_as_data_the_web_app_reads_and_a_line_in_the_run_list(saved: FakeBucket) -> None:
    assert set(saved.objects) == {"runs/2026-10-26-seed7-start1000.md", "runs/2026-10-26-seed7-start1000.json", "index/2026-10-26-seed7-start1000.json", "latest.md"}
    entry = json.loads(saved.objects["index/2026-10-26-seed7-start1000.json"])
    assert (entry["run"], entry["created"], entry["seed"], entry["replays"]) == ("2026-10-26-seed7-start1000", "2026-10-26", 7, 3)


def test_a_runs_data_says_what_its_report_says() -> None:
    settings = load_settings(SETTINGS)
    result = run_simulation(settings, seed=7, replays=3)
    data = json.loads(json.dumps(run_data(settings, result, seed=7, created=TODAY)))

    assert (data["seed"], data["replays"], [s["merchants"] for s in data["starts"]]) == (7, 3, [1000, 1500])
    for sentence in data["summary"]:
        assert sentence in result.report
    for start in data["starts"]:
        replays, detail = result.replays[start["merchants"]], result.by_start[start["merchants"]]
        for seg in start["segments"]:
            segment = Segment(seg["segment"])
            ai = next(a for a in seg["approaches"] if a["approach"] == "ai_loop")
            assert f"| {seg['label']} | AI loop | {ai['average']:+.1f} | {ai['low']:+.1f} to {ai['high']:+.1f} | {seg['ai_ahead']:,} ahead, {seg['ties']:,} tied, of 3 |" in result.report
            assert seg["weekly"]["ai_loop"] == pytest.approx(replays.weekly(segment, Approach.AI_LOOP))
            funnel = seg["funnel"]["hand_written"]
            judged, pushed = detail.outcomes[segment][Approach.HAND_WRITTEN], detail.pushed[segment][Approach.HAND_WRITTEN]
            assert (funnel["merchants"], funnel["reached"]) == (judged.counted + pushed.counted, judged.reached + pushed.reached)
        loop = start["loop"]
        assert [v["text"] for v in loop["subjects"]] == [v.text for v in detail.loop.subjects]
        assert [(o["label"], o["sent"]) for o in loop["offers"]] == [
            ("No offer", detail.offers.sent[Offer.NONE]),
            ("7 more trial days", detail.offers.sent[Offer.EXTENSION]),
            ("First month 50% off", detail.offers.sent[Offer.DISCOUNT]),
        ]
    assert [d["subject"] for d in data["first_drafts"]] == [settings.first_drafts[s.value].subject for s in Segment]


def test_the_app_lists_every_saved_run_newest_first(saved: FakeBucket) -> None:
    bucket = FakeBucket()
    bucket.objects = dict(saved.objects)
    bucket.put("index/2026-10-19-seed20261019.json", json.dumps({"run": "2026-10-19-seed20261019", "created": "2026-10-19", "seed": 20261019, "replays": 200}))

    status, content, _ = call(bucket, "GET", "/api/runs")

    assert status == 200
    assert [r["run"] for r in content["runs"]] == ["2026-10-26-seed7-start1000", "2026-10-19-seed20261019"]
    assert content["running"] == []


def test_the_app_serves_a_runs_data_and_its_report_and_nothing_else(saved: FakeBucket) -> None:
    status, content, _ = call(saved, "GET", "/api/runs/2026-10-26-seed7-start1000")
    assert status == 200 and content["seed"] == 7

    status, report, _ = call(saved, "GET", "/api/runs/2026-10-26-seed7-start1000/report")
    assert status == 200 and report == saved.objects["runs/2026-10-26-seed7-start1000.md"]

    for path in ("/api/runs/nope", "/api/runs/..%2Flatest", "/api/runs/2026-10-26-seed7-start1000/other", "/elsewhere"):
        assert call(saved, "GET", path)[0] == 404


def test_the_app_page_has_a_run_button() -> None:
    status, page, _ = call(FakeBucket(), "GET", "/")

    assert status == 200
    assert "<title>" in page and 'id="run-quick"' in page and 'id="run-full"' in page


def test_a_run_starts_only_with_the_right_access_code() -> None:
    bucket = FakeBucket()

    assert call(bucket, "POST", "/api/runs", {"code": "wrong", "replays": 20})[0] == 403
    assert call(bucket, "POST", "/api/runs", {"replays": 20})[0] == 403
    assert call(bucket, "POST", "/api/runs", {"code": "letmein", "replays": 20}, code=None)[0] == 503
    assert bucket.objects == {}

    status, content, started = call(bucket, "POST", "/api/runs", {"code": "letmein", "replays": 20})

    assert status == 202 and content == {"run": "2026-10-26-seed4242"}
    assert started == [{"seed": 4242, "replays": 20}]
    assert json.loads(bucket.objects["pending/2026-10-26-seed4242.json"])["requested"] == NOW.isoformat()


@pytest.mark.parametrize("replays", [0, 201, "20", 2.5, True])
def test_a_run_asks_for_between_1_and_200_replays(replays: object) -> None:
    assert call(FakeBucket(), "POST", "/api/runs", {"code": "letmein", "replays": replays})[0] == 400


def test_only_one_run_goes_at_a_time_and_a_finished_or_lost_one_no_longer_counts() -> None:
    bucket = FakeBucket()
    call(bucket, "POST", "/api/runs", {"code": "letmein", "replays": 20})

    status, content, _ = call(bucket, "GET", "/api/runs")
    assert [r["run"] for r in content["running"]] == ["2026-10-26-seed4242"]
    assert call(bucket, "POST", "/api/runs", {"code": "letmein", "replays": 20})[0] == 409

    # A run that never reports back stops counting after 20 minutes (the simulation's limit is 15).
    assert call(bucket, "GET", "/api/runs", now=NOW + timedelta(minutes=21))[1]["running"] == []
    # A finished run stops counting at once.
    bucket.put("index/2026-10-26-seed4242.json", json.dumps({"run": "2026-10-26-seed4242", "created": "2026-10-26", "seed": 4242, "replays": 20}))
    assert call(bucket, "GET", "/api/runs")[1]["running"] == []


def test_the_lambda_handler_answers_the_function_url(monkeypatch: pytest.MonkeyPatch, saved: FakeBucket) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeS3:
        def get_object(self, Bucket: str, Key: str) -> dict[str, object]:
            text = saved.objects.get(Key)
            if text is None:
                raise web.NoSuchKey(Key)
            return {"Body": type("Body", (), {"read": lambda self: text.encode()})()}

        def list_objects_v2(self, **kwargs: Any) -> dict[str, object]:
            return {"Contents": [{"Key": k} for k in saved.keys(kwargs["Prefix"])], "IsTruncated": False}

        def put_object(self, **kwargs: object) -> None:
            calls.append(("put_object", kwargs))

    class FakeSsm:
        def get_parameter(self, **kwargs: object) -> dict[str, object]:
            return {"Parameter": {"Value": "letmein"}}

    class FakeLambda:
        def invoke(self, **kwargs: object) -> None:
            calls.append(("invoke", kwargs))

    clients = {"s3": FakeS3(), "ssm": FakeSsm(), "lambda": FakeLambda()}
    monkeypatch.setattr("boto3.client", lambda name: clients[name])
    monkeypatch.setenv("REPORTS_BUCKET", "winback-reports")
    monkeypatch.setenv("SIMULATION_FUNCTION", "winback-SimulationFunction-abc")
    monkeypatch.setenv("ACCESS_CODE_PARAMETER", "/winback/web-access-code")

    listed = web.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/api/runs"}, None)
    assert listed["statusCode"] == 200 and "2026-10-26-seed7-start1000" in str(listed["body"])

    body = base64.b64encode(json.dumps({"code": "letmein", "replays": 20}).encode()).decode()
    started = web.handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/runs", "body": body, "isBase64Encoded": True}, None)
    assert started["statusCode"] == 202
    [(_, invoked)] = [c for c in calls if c[0] == "invoke"]
    assert invoked["FunctionName"] == "winback-SimulationFunction-abc" and invoked["InvocationType"] == "Event"
    assert json.loads(str(invoked["Payload"]))["replays"] == 20


def test_until_the_boundary_lets_it_read_reports_the_app_says_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    class AccessDenied(Exception):
        pass

    class FakeS3:
        def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
            raise AccessDenied("An error occurred (AccessDenied) when calling the ListObjectsV2 operation")

    monkeypatch.setattr("boto3.client", lambda name: FakeS3())
    monkeypatch.setenv("REPORTS_BUCKET", "winback-reports")
    monkeypatch.setenv("SIMULATION_FUNCTION", "winback-SimulationFunction-abc")
    monkeypatch.setenv("ACCESS_CODE_PARAMETER", "/winback/web-access-code")

    answer = web.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/api/runs"}, None)

    assert answer["statusCode"] == 500 and "docs/aws-setup.md" in str(answer["body"])
