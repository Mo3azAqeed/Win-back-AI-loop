"""The real writer and judge (#13), tested with fakes: free, fast and with no key."""

import json
from datetime import date
from typing import Any

import pytest

from winback import Settings, load_settings, run_simulation
from winback.copywriter import AiCopywriter, JevJudge, OpenRouterWriter, Spend, openrouter, problems
from winback.export import run_data
from winback.settings import Email

from conftest import SETTINGS, only

GOOD_SUBJECTS = ["Clone a store, then make it yours", "Skip the blank page", "{first_name}, start from a store you like"]
GOOD_BODIES = [("Hi {first_name}, clone a store to start from and make every page yours.", "Clone a store")]


class FakeWriter:
    """Writes from a script, then from a few good drafts, never repeating one already tried for this champion."""

    def __init__(self, script: list[tuple[str, str]] | None = None, model: str = "fake/writer") -> None:
        self.model, self.script, self.calls = model, list(script or []), 0
        self.feedback: list[list[str]] = []

    def write(self, slot: str, champion: Email, lessons: list[str], tried: list[str], feedback: list[str]) -> tuple[str, str, str]:
        self.calls += 1
        self.feedback.append(feedback)
        if self.script:
            text, cta = self.script.pop(0)
        else:
            drafts = [(s, "") for s in GOOD_SUBJECTS] if slot == "subject" else GOOD_BODIES
            fresh = [d for d in drafts if d[0] not in tried]
            text, cta = fresh[0] if fresh else (f"{drafts[0][0]} Start today.", drafts[0][1])
        return text, cta, f"Hypothesis for draft {self.calls}."


class FakeJudge:
    def __init__(self, rating: dict[str, float] | None = None, model: str = "fake/judge") -> None:
        self.model, self.rating = model, rating or {}
        self.asked: list[tuple[str, str, str]] = []

    def rate(self, slot: str, text: str, cta: str) -> float:
        self.asked.append((slot, text, cta))
        return self.rating.get(text, 5.0)


def settings_1000() -> Settings:
    return only(load_settings(SETTINGS), 1000)


def test_a_draft_is_rejected_for_an_invented_number_a_banned_phrase_a_fake_reply_a_long_subject_or_an_unknown_placeholder() -> None:
    settings = load_settings(SETTINGS)

    def check(slot: str, text: str, cta: str = "Go") -> list[str]:
        return problems(slot, text, cta, settings.fact_sheet, settings.writer, {"{first_name}", "{store_name}"})

    assert check("subject", "Clone a store, then make it yours") == []
    assert check("body", "Hi {first_name}, your first month is $20 instead of $40.") == []  # both prices are on the fact sheet
    assert any("$25" in p or "25" in p for p in check("body", "Hi {first_name}, your first month is $25."))
    assert any("banned phrase" in p for p in check("subject", "Copy any store in minutes"))
    assert any("reply or a forward" in p for p in check("subject", "Re: your store"))
    assert any("longer than" in p for p in check("subject", "x" * (settings.writer.subject_max_characters + 1)))
    assert any("{discount_code}" in p for p in check("body", "Use {discount_code} today"))
    assert any("button" in p for p in check("body", "Hi {first_name}, clone a store.", ""))


def test_a_rejected_draft_is_rewritten_with_the_reason_and_never_sent() -> None:
    invented = "Hi {first_name}, 9 out of 10 merchants publish in a day. Clone a store to start from."
    banned = "Copy any store you like"
    writer = FakeWriter([(banned, ""), (invented, "Clone a store")])
    copywriter = AiCopywriter(settings_1000(), writer, FakeJudge())
    start = run_simulation(settings_1000(), seed=1, copywriter=copywriter).by_start[1000]

    sent = {text for journeys in start.journeys.values() for journey in journeys for s in journey.stays for text in (s.subject, s.body)}
    assert banned not in sent and invented not in sent
    assert writer.feedback[1] and "banned phrase" in writer.feedback[1][0]  # the writer was told why
    assert len(copywriter.spend.rejected) == 2
    assert all(v.subject != banned and v.body != invented for v in start.loop.versions)


def test_the_run_refuses_a_writer_and_judge_that_are_the_same_model() -> None:
    with pytest.raises(ValueError, match="different models"):
        AiCopywriter(settings_1000(), FakeWriter(model="same/model"), FakeJudge(model="same/model"))


def test_each_variant_is_judged_once_and_written_once_for_every_replay() -> None:
    judge, writer = FakeJudge(), FakeWriter()
    run_simulation(settings_1000(), seed=1, replays=3, copywriter=AiCopywriter(settings_1000(), writer, judge))

    assert len(judge.asked) == len(set(judge.asked))  # no part judged twice
    single = FakeWriter()
    run_simulation(settings_1000(), seed=1, replays=1, copywriter=AiCopywriter(settings_1000(), single, FakeJudge()))
    assert writer.calls < 3 * single.calls  # later replays reuse what was written for the same champion


def test_the_judges_rating_against_your_first_draft_becomes_hidden_quality_plus_noise() -> None:
    settings = settings_1000()
    first = settings.first_drafts["idle"]
    judge = FakeJudge({first.subject: 5.0, "Skip the blank page": 9.0, "Still thinking about it?": 5.0})
    copywriter = AiCopywriter(settings, FakeWriter([("Skip the blank page", ""), ("Still thinking about it?", "")]), judge)
    champion = Email(first.subject, first.body, first.cta)
    better, same = copywriter.challenger("subject", champion, [], 0), copywriter.challenger("subject", champion, [], 1)

    assert better is not None and same is not None
    assert better.quality > 130  # four points above your first draft: about 1.5 times its quality
    assert 70 < same.quality < 130  # rated the same as your first draft: 100, moved only by noise
    again = AiCopywriter(settings, FakeWriter([("Skip the blank page", "")]), judge).challenger("subject", champion, [], 0)
    assert again is not None and again.quality == better.quality  # the same words always get the same noise


def test_with_the_ai_writer_versions_say_who_wrote_them_and_the_report_says_what_it_cost() -> None:
    result = run_simulation(settings_1000(), seed=1, copywriter=AiCopywriter(settings_1000(), FakeWriter(), FakeJudge()))
    later = result.by_start[1000].loop.versions[1:]

    assert later and all(v.by == "AI writer (fake/writer)" and v.hypothesis.startswith("Hypothesis for draft") for v in later)
    assert "## Writer and judge" in result.report and "Written by fake/writer, judged by fake/judge" in result.report
    assert "stand-in writer's" not in result.report.split("## Placeholders")[1]


def test_the_stand_in_writer_stays_the_default_and_its_report_has_no_writer_section() -> None:
    result = run_simulation(settings_1000(), seed=1)

    assert "## Writer and judge" not in result.report
    assert "writer.quality_per_point" not in result.report
    assert all(v.by in ("you", "stand-in writer") for v in result.by_start[1000].loop.versions)


def fake_openrouter(log: list[tuple[str, dict[str, Any], str]]) -> Any:
    def post(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        log.append((url, payload, api_key))
        if url.endswith("/decisions"):
            return {"answers": {"appeal": {"type": "score", "score": 6.2, "probabilities": {}, "confidence": 0.7}}, "usage": {"cost": 0.0001}}
        slot = "body" if "new body" in payload["messages"][1]["content"] else "subject"
        answer = {"text": "Clone a store, then make it yours", "button": "", "hypothesis": "Names cloning."} if slot == "subject" else {
            "text": "Hi {first_name}, clone a store to start from.", "button": "Clone a store", "hypothesis": "Shorter."}
        return {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"cost": 0.0002}}
    return post


def test_the_openrouter_writer_and_jev_judge_send_the_right_requests_and_read_the_answers() -> None:
    log: list[tuple[str, dict[str, Any], str]] = []
    copywriter = openrouter(settings_1000(), "sk-or-test-key", fake_openrouter(log))
    first = settings_1000().first_drafts["idle"]
    variant = copywriter.challenger("subject", Email(first.subject, first.body, first.cta), ["v1 lost."], 0)

    assert variant is not None and variant.text == "Clone a store, then make it yours" and variant.hypothesis == "Names cloning."
    judged = [p for url, p, _ in log if url == "https://openrouter.ai/api/alpha/decisions"]
    written = [p for url, p, _ in log if url == "https://openrouter.ai/api/v1/chat/completions"]
    assert judged and all(p["model"] == "typesafe/jev-1.14" and p["questions"]["appeal"]["type"] == "score" and len(p["questions"]["appeal"]["criteria"]) == 10 for p in judged)
    assert written and written[0]["model"] == "deepseek/deepseek-v4.1-flash-1017" and written[0]["response_format"]["type"] == "json_schema"
    assert "v1 lost." in written[0]["messages"][1]["content"]  # the lessons reach the writer
    assert "$40/month" in written[0]["messages"][0]["content"]  # and so does the fact sheet
    assert all(key == "sk-or-test-key" for _, _, key in log)
    assert copywriter.spend.cost > 0


def test_no_api_key_is_ever_written_to_the_report_or_the_run_data() -> None:
    settings = settings_1000()
    result = run_simulation(settings, seed=1, copywriter=openrouter(settings, "sk-or-secret-123", fake_openrouter([])))
    data = json.dumps(run_data(settings, result, seed=1, created=date(2026, 10, 26)))

    assert "sk-or-secret-123" not in result.report and "sk-or-secret-123" not in data
    assert result.by_start[1000].loop.versions[1].by == "AI writer (deepseek/deepseek-v4.1-flash-1017)"


def test_a_judge_answer_that_is_not_a_score_fails_clearly() -> None:
    judge = JevJudge("typesafe/jev-1.14", "key", Spend(), lambda url, payload, key: {"error": "model moved"})
    with pytest.raises(RuntimeError, match="Decisions API"):
        judge.rate("subject", "Hello", "")
    writer = OpenRouterWriter("deepseek/x", "key", settings_1000().fact_sheet, Spend(), lambda url, payload, key: {"choices": []})
    with pytest.raises(RuntimeError, match="JSON"):
        writer.write("subject", Email("a", "b", "c"), [], [], [])
