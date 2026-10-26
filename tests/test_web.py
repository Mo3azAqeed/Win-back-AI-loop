import base64
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from winback import Approach, Offer, Segment, load_settings, run_simulation
from winback import web
from winback.aws import run_and_save
from winback.export import run_data
from winback.web import respond

from conftest import SETTINGS

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


def test_the_app_page_lets_you_write_your_emails_and_simulate() -> None:
    status, page, _ = call(FakeBucket(), "GET", "/")

    assert status == 200
    assert "<title>Win-back Lab</title>" in page and "Simulate 13 weeks" in page and "/api/drafts" in page


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


def test_each_stage_has_a_week_by_week_story_of_what_was_sent_written_and_dropped() -> None:
    settings = load_settings(SETTINGS)
    result = run_simulation(settings, seed=7, replays=2)
    data = run_data(settings, result, seed=7, created=TODAY)
    detail = result.by_start[1000]
    segments = {s["segment"]: s for s in data["starts"][0]["segments"]}

    idle = segments["idle"]["weeks"]
    assert [w["week"] for w in idle] == list(range(1, 16))
    # Your first drafts are where the AI loop starts, in week 1.
    assert {(c["text"], c["by"]) for c in idle[0]["ai"]["written"]} >= {(settings.first_drafts["idle"].subject, "you"), (settings.first_drafts["idle"].body, "you")}
    written = [c for w in idle for c in w["ai"]["written"]]
    dropped = [c for w in idle for c in w["ai"]["dropped"]]
    assert dropped and len(written) == len(detail.loop.subjects) + len(detail.loop.bodies)
    # A dropped email is never the one leading at the end of its week, and was judged on enough sends.
    for w in idle:
        for c in w["ai"]["dropped"]:
            assert c["text"] not in (w["ai"]["leading"]["subject"], w["ai"]["leading"]["body"])
            assert c["sends"] >= settings.loop.min_sends
    # Drafters and Trialists send their own first draft every week, and their words never change.
    for segment in ("drafter", "trialist"):
        for w in segments[segment]["weeks"]:
            assert w["ai"]["leading"]["subject"] == settings.first_drafts[segment].subject
            assert w["ai"]["written"] == w["ai"]["dropped"] == []
    # Only Trialist emails carry offers.
    assert any(w["ai"]["offers"] for w in segments["trialist"]["weeks"]) and not any(w["ai"]["offers"] for w in idle)
    # Every email sent by week 15 is counted in its week, and a goal action needs a send.
    sent = sum(s.segment is Segment.IDLE and s.email_sent_at is not None and s.email_sent_at <= 105 and s.email.value == "sent" for j in detail.journeys[Approach.HAND_WRITTEN] for s in j.stays)
    assert sum(w["hand"]["sent"] for w in idle) == sent
    assert all(w[a]["clicks"] <= w[a]["sent"] and w[a]["goal_actions"] <= w[a]["sent"] for w in idle for a in ("hand", "ai"))


YOUR_EMAILS = [
    {"segment": "idle", "subject": "Your store is waiting", "body": "Hi {first_name}, clone a store you like and make it yours.", "cta": "Clone a store", "send_after": "1 hour"},
    {"segment": "drafter", "subject": "Publish {store_name} today", "body": "Hi {first_name}, one click and your 7-day free trial starts.", "cta": "Publish", "send_after": "2 days"},
    {"segment": "trialist", "subject": "Keep {store_name} going", "body": "Hi {first_name}, keep your store for $40/month.", "cta": "Keep it", "send_after": "5 days"},
]


def test_the_editor_starts_from_your_current_first_drafts() -> None:
    settings = load_settings(SETTINGS)
    status, content, _ = call(FakeBucket(), "GET", "/api/drafts")

    assert status == 200
    assert [(e["segment"], e["subject"], e["cta"], e["send_after"]) for e in content["emails"]] == [
        (s.value, settings.first_drafts[s.value].subject, settings.first_drafts[s.value].cta, "2 days") for s in Segment
    ]


def test_a_run_from_the_app_carries_the_emails_you_wrote() -> None:
    status, _, started = call(FakeBucket(), "POST", "/api/runs", {"code": "letmein", "replays": 20, "emails": YOUR_EMAILS})

    assert status == 202
    assert started == [{"seed": 4242, "replays": 20, "emails": YOUR_EMAILS}]


@pytest.mark.parametrize(
    "emails",
    [
        YOUR_EMAILS[:2],  # a stage missing
        [{**YOUR_EMAILS[0], "send_after": "3 days"}, *YOUR_EMAILS[1:]],  # a timing the simulation can't test
        [{**YOUR_EMAILS[0], "subject": ""}, *YOUR_EMAILS[1:]],  # an empty subject
        [{**YOUR_EMAILS[0], "body": "x" * 3001}, *YOUR_EMAILS[1:]],  # far too long
        "not a list",
    ],
)
def test_emails_that_cant_be_simulated_are_refused(emails: object) -> None:
    assert call(FakeBucket(), "POST", "/api/runs", {"code": "letmein", "replays": 20, "emails": emails})[0] == 400


def test_the_simulation_sends_your_emails_as_the_hand_written_email_and_starts_the_ai_loop_from_them() -> None:
    bucket = FakeBucket()
    run_and_save({"seed": 7, "start": 1000, "replays": 1, "emails": YOUR_EMAILS}, today=TODAY, settings_path=SETTINGS, put=bucket.put)
    data = json.loads(bucket.objects["runs/2026-10-26-seed7-start1000.json"])

    assert [(e["subject"], e["send_after_days"]) for e in data["first_drafts"]] == [("Your store is waiting", 1 / 24), ("Publish {store_name} today", 2), ("Keep {store_name} going", 5)]
    loop = data["starts"][0]["loop"]
    assert loop["subjects"][0]["text"] == "Your store is waiting" and loop["bodies"][0]["cta"] == "Clone a store"
    assert [c["subject"] for c in loop["segment_copy"]] == ["Publish {store_name} today", "Keep {store_name} going"]
    assert "Your store is waiting" in bucket.objects["runs/2026-10-26-seed7-start1000.md"]


def test_every_version_shows_how_it_did_against_your_email() -> None:
    settings = load_settings(SETTINGS)
    result = run_simulation(settings, seed=7, replays=1)
    segments = {s["segment"]: s for s in run_data(settings, result, seed=7, created=TODAY)["starts"][0]["segments"]}
    detail = result.by_start[1000]

    idle = segments["idle"]["versions"]
    # Every subject and body the AI loop tried is listed once, your first draft first.
    assert [v["text"] for v in idle["ai"] if v["part"] == "subject"] == [v.text for v in detail.loop.subjects]
    assert idle["ai"][0]["by"] == "you" and idle["ai"][0]["written_week"] == 1
    # Each email the AI loop sent counts once for its subject and once for its body.
    ai_sent = sum(s.segment is Segment.IDLE and s.email.value == "sent" for j in detail.journeys[Approach.AI_LOOP] for s in j.stays)
    assert sum(v["sends"] for v in idle["ai"] if v["part"] == "subject") == sum(v["sends"] for v in idle["ai"] if v["part"] == "body") == ai_sent
    # Worked example of "against yours": a version's rate minus your email's, in points.
    yours = idle["yours"]
    for v in idle["ai"]:
        if v["sends"]:
            assert v["click_rate_vs_yours"] == pytest.approx((v["clicks"] / v["sends"] - yours["clicks"] / yours["sends"]) * 100)
        if v["status"] == "dropped":
            assert v["dropped_week"] is not None and v["dropped_week"] >= v["written_week"]
    # A secretly better version clicks better than your email; a dropped weak one does worse.
    best = max((v for v in idle["ai"] if v["sends"] > 300), key=lambda v: v["click_rate"])
    assert best["click_rate_vs_yours"] > 0
    assert [o["label"] for o in segments["trialist"]["versions"]["offers"]] == ["No offer", "7 more trial days", "First month 50% off"]
    assert segments["drafter"]["versions"]["offers"] == []


def test_every_version_can_be_downloaded_as_a_spreadsheet(saved: FakeBucket) -> None:
    status, csv_text, _ = call(saved, "GET", "/api/runs/2026-10-26-seed7-start1000/versions.csv")

    lines = csv_text.strip().splitlines()
    assert status == 200
    assert lines[0] == "merchants,stage,version,part,words,button,written_by,status,from_week,dropped_week,sends,click_rate,goal_rate,click_vs_yours_pts,goal_vs_yours_pts"
    data = json.loads(saved.objects["runs/2026-10-26-seed7-start1000.json"])
    idle = data["starts"][0]["segments"][0]["versions"]
    assert len(lines) == 1 + sum(1 + len(s["versions"]["ai"]) + len(s["versions"]["offers"]) for s in data["starts"][0]["segments"])
    assert lines[1].startswith("1000,Idle,Your email,email,")
    assert any(idle["ai"][1]["text"] in line for line in lines)
