import dataclasses
import re
import tomllib

import pytest

from winback import Approach, RunResult, Segment, Settings, StartResult, load_settings, run_simulation
from winback.lifecycle import EmailFate
from winback.outcomes import SegmentOutcome

from conftest import ROOT, SETTINGS, only, with_segment

def test_the_stand_in_writers_list_has_at_least_8_subjects_and_8_bodies_within_the_fact_sheet() -> None:
    settings = load_settings(SETTINGS)
    fact_sheet = tomllib.loads((ROOT / "fact_sheet.toml").read_text())
    facts = " ".join(str(v) for section in fact_sheet.values() for v in section.values())
    allowed_numbers = set(re.findall(r"\d+", facts))
    banned = fact_sheet["rules"]["banned_phrases"]

    assert len(settings.prewritten_subjects) >= 8 and len(settings.prewritten_bodies) >= 8
    for variant in (*settings.prewritten_subjects, *settings.prewritten_bodies):
        words = f"{variant.text} {variant.cta}".lower()
        assert set(re.findall(r"\d+", words)) <= allowed_numbers, variant.text
        assert not any(phrase in words for phrase in banned), variant.text
        assert not words.startswith(("re:", "fwd:")), variant.text
        assert variant.quality > 0
        assert variant.hypothesis, variant.text  # every challenger says what it changes and why


def with_subjects(settings: Settings, *qualities: float) -> Settings:
    subjects = tuple(dataclasses.replace(v, quality=q) for v, q in zip(settings.prewritten_subjects, qualities))
    return dataclasses.replace(settings, prewritten_subjects=subjects + settings.prewritten_subjects[len(qualities):])


def with_carry_over(settings: Settings, carry_over: float) -> Settings:
    return dataclasses.replace(settings, loop=dataclasses.replace(settings.loop, carry_over=carry_over))


def test_the_ai_loop_starts_from_your_first_drafts(run: RunResult) -> None:
    settings = load_settings(SETTINGS)
    loop = run.by_start[1000].loop

    assert (loop.subjects[0].text, loop.subjects[0].quality) == (settings.first_drafts["idle"].subject, 100)
    assert (loop.bodies[0].text, loop.bodies[0].cta, loop.bodies[0].quality) == (settings.first_drafts["idle"].body, settings.first_drafts["idle"].cta, 100)
    assert [v.text for v in loop.subjects[1:]] == [v.text for v in settings.prewritten_subjects[: len(loop.subjects) - 1]]


def test_the_ai_loop_never_emails_the_holdout_and_keeps_the_sending_rules(run: RunResult) -> None:
    journeys = run.by_start[1000].journeys[Approach.AI_LOOP]
    held = {j.merchant.key for j in journeys if j.merchant.holdout}

    assert not any(r.merchant_key in held for r in run.by_start[1000].email_results[Approach.AI_LOOP])
    for journey in journeys:
        sent = [s for s in journey.stays if s.email_sent_at is not None]
        assert len({s.segment for s in sent}) == len(sent)
        days = [s.email_sent_at for s in sent if s.email_sent_at is not None]
        assert all(later - earlier >= 2 - 1e-9 for earlier, later in zip(days, days[1:]))
        assert all(not journey.merchant.holdout for s in sent if s.email is EmailFate.SENT)


def test_judging_timing_by_everyone_assigned_does_not_favour_a_truly_worse_early_timing() -> None:
    # Drafters read an email sent 1 hour after saving far less (read shift -2), so +1 hour is truly worst.
    # A third of Drafters publish on their own within days, which a judge counting the window after the
    # email would credit to the early email. Judged by everyone assigned, from the trigger, +1 hour gets
    # under a third of Drafters on average and is never ahead (one seed can be lucky, so six are used).
    # The email has to matter enough for 13 weeks to tell timings apart: with the placeholder Drafter
    # rates, +1 hour leads in about a third of seeds whichever judge is used.
    settings = with_segment(load_settings(SETTINGS), Segment.DRAFTER, read_shift_1_hour=-2.0, click_rate=0.5, act_rate=1.0)
    settings = only(settings, 1000)
    shares, ahead = [], 0
    for seed in range(1, 7):
        timings = run_simulation(settings, seed=seed).by_start[1000].loop.timings[Segment.DRAFTER]
        early = next(t for t in timings if t.label == "+1 hour")
        shares.append(early.assigned / sum(t.assigned for t in timings))
        ahead += early.leading

    assert sum(shares) / len(shares) < 0.3
    assert ahead == 0


def test_the_report_compares_the_ai_loop_with_the_hand_written_email_and_shows_its_timings(run: RunResult) -> None:
    # Idle's versions and playbook have their own tests (test_versions.py).
    start = run.by_start[1000]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]

    for segment in Segment:
        ai = start.outcomes[segment][Approach.AI_LOOP]
        assert f"| AI loop | {ai.counted:,} | {ai.reached_share:.1%} | {ai.true_lift * 100:+.1f} |" in from_1000
    for segment in Segment:
        leading_timing = next(t for t in start.loop.timings[segment] if t.leading)
        assert leading_timing.label in from_1000


def test_only_idle_emails_teach_subjects_and_bodies(run: RunResult) -> None:
    # Drafters and Trialists send their own first drafts; their clicks teach nothing about Idle's words.
    start = run.by_start[1000]
    idle_sent = start.outcomes[Segment.IDLE][Approach.AI_LOOP].emails.sent

    assert sum(v.sends for v in start.loop.subjects) == sum(v.sends for v in start.loop.bodies) == idle_sent


def test_an_early_email_held_back_by_the_48_hour_gap_is_read_as_when_it_really_arrives() -> None:
    # Nobody reads a Drafter email sent within the first hour (read shift -10). But every Drafter here is
    # a new one who drafted minutes after an Idle email (there are no existing Drafters), so an email planned for +1 hour is held back by the 48-hour gap
    # and arrives about 2 days in, when it is read as often as a +2 days email (43%, and then clicked and
    # acted on for certain). Nobody publishes on their own, so only the email can make them publish.
    certain = {"organic_share": 0.0, "read_rate": 1.0, "click_rate": 1.0, "act_rate": 1.0, "response_mean_days": 0.001}
    settings = with_segment(load_settings(SETTINGS), Segment.IDLE, **certain)
    settings = with_segment(settings, Segment.DRAFTER, organic_share=0.0, click_rate=1.0, act_rate=1.0, read_shift_1_hour=-10.0)
    settings = dataclasses.replace(settings, existing_shares={**settings.existing_shares, Segment.DRAFTER: 0.0})
    early = next(t for t in run_simulation(settings, seed=1).by_start[1000].loop.timings[Segment.DRAFTER] if t.label == "+1 hour")

    assert early.assigned > 20
    assert 0.3 < early.reached / early.assigned < 0.56


def test_drafters_and_trialists_get_their_own_first_drafts_never_idle_words(run: RunResult) -> None:
    settings = load_settings(SETTINGS)
    start = run.by_start[1000]
    idle_words = {v.text for v in (*start.loop.subjects, *start.loop.bodies)}

    for segment in (Segment.DRAFTER, Segment.TRIALIST):
        copy, draft = start.loop.segment_copy[segment], settings.first_drafts[segment.value]
        sent = sum(s.segment is segment and s.email is EmailFate.SENT for j in start.journeys[Approach.AI_LOOP] for s in j.stays)
        assert (copy.subject, copy.body, copy.cta) == (draft.subject, draft.body, draft.cta)
        assert not {copy.subject, copy.body} & idle_words
        assert copy.sends == sent > 0


def test_with_no_carry_over_drafter_and_trialist_emails_do_as_well_as_their_first_drafts_whatever_idle_finds() -> None:
    # Idle soon finds a subject and a body far better than your first draft (hidden quality 400 and 300).
    # Timing doesn't change reading here, so every Drafter or Trialist email is read and clicked exactly as
    # often as its first draft (read rate x click rate), unless some of Idle's edge carries over.
    settings = with_subjects(load_settings(SETTINGS), 400)
    settings = dataclasses.replace(only(settings, 1000), prewritten_bodies=(dataclasses.replace(settings.prewritten_bodies[0], quality=300), *settings.prewritten_bodies[1:]))
    for segment in (Segment.DRAFTER, Segment.TRIALIST):
        settings = with_segment(settings, segment, read_shift_1_hour=0.0, read_shift_5_days=0.0)

    for segment in (Segment.DRAFTER, Segment.TRIALIST):
        behaviour = settings.segments[segment]
        expected = behaviour.read_rate * behaviour.click_rate
        none = run_simulation(with_carry_over(settings, 0.0), seed=1).by_start[1000].loop.segment_copy[segment]
        full = run_simulation(with_carry_over(settings, 1.0), seed=1).by_start[1000].loop.segment_copy[segment]
        margin = 3 * (expected * (1 - expected) / none.sends) ** 0.5

        assert abs(none.clicks / none.sends - expected) < margin, segment
        assert full.clicks / full.sends > expected + 2 * margin, segment


def test_changing_the_carry_over_never_changes_idle_results() -> None:
    # A secretly much better first challenger is crowned, so Idle's champion has an edge to carry over.
    settings = with_subjects(only(load_settings(SETTINGS), 1000), 300)
    none, full = (run_simulation(with_carry_over(settings, c), seed=1).by_start[1000] for c in (0.0, 1.0))

    # Paying within 30 days of signing up depends on the Trialist email that comes later, so it may change.
    def idle(start: StartResult) -> dict[Approach, SegmentOutcome]:
        return {a: dataclasses.replace(o, paid_in_window=0) for a, o in start.outcomes[Segment.IDLE].items()}

    assert idle(none) == idle(full)
    assert (none.loop.subjects, none.loop.bodies, none.loop.timings[Segment.IDLE]) == (full.loop.subjects, full.loop.bodies, full.loop.timings[Segment.IDLE])
    assert none.outcomes[Segment.TRIALIST] != full.outcomes[Segment.TRIALIST]


def test_the_report_states_the_carry_over_it_used() -> None:
    settings = only(with_carry_over(load_settings(SETTINGS), 0.5), 1000)
    report = run_simulation(settings, seed=1).report

    assert "Carry-over from Idle: 50%" in report


def test_a_carry_over_outside_0_to_1_is_refused() -> None:
    for carry_over in (-0.1, 1.5):
        with pytest.raises(ValueError, match="carry_over"):
            run_simulation(with_carry_over(load_settings(SETTINGS), carry_over), seed=1)


def test_by_default_none_of_idles_edge_carries_over_and_the_report_shows_each_segments_own_email(run: RunResult) -> None:
    start = run.by_start[1000]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]

    assert start.loop.carry_over == 0
    assert "Carry-over from Idle: 0%" in from_1000
    for segment in (Segment.DRAFTER, Segment.TRIALIST):
        copy = start.loop.segment_copy[segment]
        assert f"| {segment.value.title()} | {copy.subject}: {copy.body} **[{copy.cta}]** | {copy.sends:,} |" in from_1000
