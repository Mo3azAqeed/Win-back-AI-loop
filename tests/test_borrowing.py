"""Drafters and Trialists borrow Idle's playbook (#36): when an Idle test is won, the writer applies the same
change to their emails in their own words, and the new version replaces the old one with no test of its own."""

import dataclasses

from winback import Segment, Settings, load_settings, run_simulation
from winback.copywriter import AiCopywriter, problems
from winback.loop import Ending, LoopReport
from winback.settings import Variant

from conftest import SETTINGS, only, with_segment
from test_copywriter import FakeJudge, FakeWriter

BORROWERS = (Segment.DRAFTER, Segment.TRIALIST)


def with_carry_over(settings: Settings, carry_over: float) -> Settings:
    return dataclasses.replace(settings, loop=dataclasses.replace(settings.loop, carry_over=carry_over))


def better_first_subject(settings: Settings, quality: float = 300) -> Settings:
    """The first challenger (a new subject) is secretly much better, so Idle crowns it."""
    first = dataclasses.replace(settings.prewritten_subjects[0], quality=quality)
    return dataclasses.replace(settings, prewritten_subjects=(first, *settings.prewritten_subjects[1:]))


def nothing_to_borrow(settings: Settings) -> Settings:
    """The stand-in writer has no Drafter or Trialist words for any change, so nothing is ever borrowed."""
    def strip(variants: tuple[Variant, ...]) -> tuple[Variant, ...]:
        return tuple(dataclasses.replace(v, adapted=()) for v in variants)

    return dataclasses.replace(settings, prewritten_subjects=strip(settings.prewritten_subjects), prewritten_bodies=strip(settings.prewritten_bodies))


def loop_of(settings: Settings, seed: int = 1) -> LoopReport:
    return run_simulation(only(settings, 1000), seed=seed).by_start[1000].loop


def test_when_an_idle_test_is_won_drafter_and_trialist_get_a_version_applying_the_same_change_in_their_own_words() -> None:
    settings = better_first_subject(load_settings(SETTINGS))
    loop = loop_of(settings)
    won = loop.playbook[0]
    assert (won.challenger, won.ending) == (1, Ending.CHALLENGER_WON)

    for segment in BORROWERS:
        first, borrowed = loop.segment_versions[segment][:2]
        draft = settings.first_drafts[segment.value]
        assert (first.number, first.subject, first.body, first.borrowed_from_test) == (0, draft.subject, draft.body, None)
        words = settings.prewritten_subjects[0].adaptation(segment.value)
        assert words is not None
        assert (borrowed.number, borrowed.subject, borrowed.body, borrowed.cta) == (1, words[0], draft.body, draft.cta)
        assert (borrowed.borrowed_from_test, borrowed.idle_version, borrowed.changed) == (won.test, won.challenger, "subject")
        assert borrowed.hypothesis == won.hypothesis and borrowed.day == won.ended


def test_only_won_idle_tests_are_borrowed_not_ones_kept_at_the_limit() -> None:
    kept = 0
    for seed in (1, 2, 3):
        loop = loop_of(better_first_subject(load_settings(SETTINGS)), seed)
        won = [e.test for e in loop.playbook if e.ending is Ending.CHALLENGER_WON]
        kept += sum("kept, not proven" in e.conclusion for e in loop.playbook)
        assert won, seed
        for segment in BORROWERS:
            assert [v.borrowed_from_test for v in loop.segment_versions[segment][1:]] == won, seed
    assert kept  # versions kept at a test's limit were there to borrow, and weren't


def test_with_carry_over_0_borrowing_leaves_every_result_unchanged_and_the_report_says_so() -> None:
    settings = only(better_first_subject(load_settings(SETTINGS)), 1000)
    borrowing = run_simulation(settings, seed=1)
    not_borrowing = run_simulation(nothing_to_borrow(settings), seed=1)

    assert len(borrowing.by_start[1000].loop.segment_versions[Segment.DRAFTER]) > 1
    assert borrowing.by_start[1000].outcomes == not_borrowing.by_start[1000].outcomes
    assert "a borrowed change gets no simulated boost, so their results are the same as without it" in borrowing.report


def test_with_carry_over_1_borrowing_a_truly_better_change_raises_their_click_rate() -> None:
    # Timing doesn't change reading here, so a Drafter or Trialist email is clicked as often as its words make it.
    settings = with_carry_over(only(better_first_subject(load_settings(SETTINGS), quality=400), 1000), 1.0)
    for segment in BORROWERS:
        settings = with_segment(settings, segment, read_shift_1_hour=0.0, read_shift_5_days=0.0)

    borrowing = run_simulation(settings, seed=1).by_start[1000].loop
    not_borrowing = run_simulation(nothing_to_borrow(settings), seed=1).by_start[1000].loop
    for segment in BORROWERS:
        before, after = (loop.segment_copy[segment] for loop in (not_borrowing, borrowing))
        assert after.clicks / after.sends > before.clicks / before.sends + 0.01, segment
        # The borrowed version itself beats the first draft it replaced.
        first, borrowed = borrowing.segment_versions[segment][:2]
        assert borrowed.clicks / borrowed.sends > first.clicks / first.sends, segment


def test_the_report_lists_each_segments_versions_and_the_idle_test_each_was_borrowed_from() -> None:
    result = run_simulation(only(better_first_subject(load_settings(SETTINGS)), 1000), seed=1)
    report = result.report.split("## Starting from 1,000 merchants", 1)[1]
    loop = result.by_start[1000].loop

    for segment in BORROWERS:
        borrowed = loop.segment_versions[segment][1]
        assert f"borrowed from Idle test {borrowed.borrowed_from_test} (v{borrowed.idle_version}, new {borrowed.changed})" in report
        assert borrowed.subject in report


def test_every_stand_in_adaptation_passes_the_writers_checks() -> None:
    settings = load_settings(SETTINGS)
    placeholders = {"{first_name}", "{store_name}", "{trial_end_date}"}
    for variant in (*settings.prewritten_subjects, *settings.prewritten_bodies):
        slot = "body" if variant.cta else "subject"
        for segment in BORROWERS:
            words = variant.adaptation(segment.value)
            assert words is not None, variant.text
            assert problems(slot, words[0], words[1], settings.fact_sheet, settings.writer, placeholders) == [], words


def test_the_ai_writer_adapts_a_won_change_once_per_segment_through_the_same_checks() -> None:
    settings = only(load_settings(SETTINGS), 1000)
    writer = FakeWriter(script=[("Hi {first_name}, publish {store_name} and get 3 free months.", "Publish")])
    copywriter = AiCopywriter(settings, writer, FakeJudge())
    draft = settings.first_drafts["drafter"]

    for _ in range(2):  # asked twice, written once
        words = copywriter.adapt("drafter", "body", draft, "Hi {first_name}, clone a store.", "Clone a store", "Shorter.")
    assert words is not None and "3 free months" not in words[0]
    assert writer.feedback[-1]  # the draft with an invented offer was rejected and rewritten with the reason
    assert len([r for r in copywriter.spend.rejected if "3 free months" in r]) == 1


def test_a_won_change_a_segment_has_no_words_for_is_reported_and_the_segment_keeps_its_email() -> None:
    settings = better_first_subject(load_settings(SETTINGS))
    first = settings.prewritten_subjects[0]
    no_trialist_words = dataclasses.replace(first, adapted=tuple(a for a in first.adapted if a[0] != "trialist"))
    settings = dataclasses.replace(settings, prewritten_subjects=(no_trialist_words, *settings.prewritten_subjects[1:]))

    result = run_simulation(only(settings, 1000), seed=1)
    loop = result.by_start[1000].loop

    assert [v.borrowed_from_test for v in loop.segment_versions[Segment.DRAFTER]][1] == 1
    assert len(loop.segment_versions[Segment.TRIALIST]) == 1 or loop.segment_versions[Segment.TRIALIST][1].borrowed_from_test != 1
    assert [(n.segment, n.test) for n in loop.not_borrowed][:1] == [(Segment.TRIALIST, 1)]
    assert "Idle test 1's change wasn't borrowed by Trialists" in result.report
