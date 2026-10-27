"""Idle versions: your email is version 0, each challenger is tested against the champion, and every test
ends in a verdict written to the playbook (#34)."""

import dataclasses

from winback import Segment, Settings, load_settings, run_simulation
from winback.loop import Ending, LoopReport

from conftest import SETTINGS, only, with_segment

DAYS_PER_WEEK = 7


def first_subject(settings: Settings, quality: float, follow_through: float = 100.0) -> Settings:
    """The first challenger (version 1) changes the subject: here to a stand-in subject with this hidden truth."""
    subjects = settings.prewritten_subjects
    first = dataclasses.replace(subjects[0], quality=quality, follow_through=follow_through)
    return dataclasses.replace(settings, prewritten_subjects=(first, *subjects[1:]))


def all_identical(settings: Settings) -> Settings:
    """Every subject and body the writer has is secretly exactly as good as your first draft."""
    return dataclasses.replace(
        settings,
        prewritten_subjects=tuple(dataclasses.replace(v, quality=100) for v in settings.prewritten_subjects),
        prewritten_bodies=tuple(dataclasses.replace(v, quality=100) for v in settings.prewritten_bodies),
    )


def loop_of(settings: Settings, seed: int = 1) -> LoopReport:
    return run_simulation(only(settings, 1000), seed=seed).by_start[1000].loop


def test_version_0_is_your_email_and_every_later_version_has_a_number_a_hypothesis_and_an_author() -> None:
    settings = load_settings(SETTINGS)
    loop = loop_of(settings)
    draft = settings.first_drafts["idle"]
    v0, *later = loop.versions

    assert (v0.number, v0.subject, v0.body, v0.cta, v0.by) == (0, draft.subject, draft.body, draft.cta, "you")
    assert later, "the writer brought at least one challenger"
    assert [v.number for v in later] == list(range(1, len(later) + 1))
    hypotheses = {v.text: v.hypothesis for v in (*settings.prewritten_subjects, *settings.prewritten_bodies)}
    for version in later:
        assert version.by == "stand-in writer"
        changed = version.subject if version.changed == "subject" else version.body
        assert version.hypothesis == hypotheses[changed] != ""


def test_a_challenger_changes_one_part_of_the_champion_it_was_tested_against() -> None:
    loop = loop_of(load_settings(SETTINGS))
    versions = {v.number: v for v in loop.versions}

    for entry in loop.playbook:
        champion, challenger = versions[entry.champion], versions[entry.challenger]
        same = [part for part in ("subject", "body") if getattr(champion, part) == getattr(challenger, part)]
        assert len(same) == 1 and challenger.changed not in same


def test_one_champion_and_one_challenger_at_a_time_and_every_test_ends_in_one_of_four_ways() -> None:
    settings = load_settings(SETTINGS)
    loop = loop_of(settings)
    limit = settings.loop.test_max_weeks * DAYS_PER_WEEK

    assert loop.playbook
    for earlier, later in zip(loop.playbook, loop.playbook[1:]):
        assert later.started >= earlier.ended  # tests never overlap
        # The next challenger enters as soon as a test ends, so nothing waits.
        assert later.started == earlier.ended
    for entry in loop.playbook:
        assert entry.ending in Ending
        assert entry.ended - entry.started <= limit
        # Judged once: when both versions reach their planned emails, or at the time limit.
        assert min(entry.champion_sends, entry.challenger_sends) <= settings.loop.test_sends
        assert entry.conclusion
    tested = [e.challenger for e in loop.playbook]
    assert len(set(tested)) == len(tested)  # each challenger gets one test
    # Every week has one champion, and at most one challenger.
    assert all(isinstance(w.champion, int) for w in loop.weekly_leaders)


def test_a_secretly_better_challenger_is_crowned() -> None:
    for seed in (1, 2, 3):
        loop = loop_of(first_subject(load_settings(SETTINGS), quality=300), seed)
        first = loop.playbook[0]

        assert (first.champion, first.challenger, first.ending) == (0, 1, Ending.CHALLENGER_WON), seed
        assert loop.weekly_leaders[-1].champion >= 1
        assert "crowned" in first.conclusion
        assert next(v for v in loop.versions if v.number == 0).sunset_day == first.ended


def test_a_secretly_worse_challenger_is_sunset_with_an_entry_saying_it_lost() -> None:
    for seed in (1, 2, 3):
        loop = loop_of(first_subject(load_settings(SETTINGS), quality=20), seed)
        first = loop.playbook[0]
        v1 = next(v for v in loop.versions if v.number == 1)

        assert (first.challenger, first.ending) == (1, Ending.CHAMPION_WON), seed
        assert first.challenger_clicks / first.challenger_sends < first.champion_clicks / first.champion_sends
        assert "lost" in first.conclusion and "sunset" in first.conclusion
        assert v1.sunset_day == first.ended and v1.crowned_day is None


def test_a_challenger_with_more_clicks_but_clearly_fewer_goal_actions_is_not_crowned() -> None:
    # Hidden truth: version 1's subject wins three times the reads, but a merchant who clicks it acts
    # a twentieth as often (it oversells). Nobody starts a draft on their own, so only clicks lead to goals.
    settings = with_segment(load_settings(SETTINGS), Segment.IDLE, organic_share=0.0, act_rate=0.9, response_mean_days=0.1)
    for seed in (1, 2, 3):
        loop = loop_of(first_subject(settings, quality=300, follow_through=5), seed)
        first = loop.playbook[0]

        assert first.challenger_clicks / first.challenger_sends > first.champion_clicks / first.champion_sends, seed
        assert first.ending is Ending.CHAMPION_WON, seed
        assert "fewer goal actions" in first.conclusion


def test_with_every_version_secretly_identical_every_test_still_ends_and_few_crown_a_challenger() -> None:
    settings = all_identical(load_settings(SETTINGS))
    limit, sure = settings.loop.test_max_weeks * DAYS_PER_WEEK, settings.loop.verdict_confidence
    entries = []
    for seed in range(1, 21):
        loop = loop_of(settings, seed)
        entries += loop.playbook
        # A new challenger enters every time a test ends, until the writer runs out.
        assert len(loop.versions) == len(loop.playbook) + 1 + (loop.weekly_leaders[-1].challenger is not None), seed
        assert all(e.ended - e.started <= limit + 1e-9 for e in loop.playbook)

    # Each test is judged once, so a fake crowning happens about as often as the bar allows (1 - sure, about 5%),
    # not more: judging every week would let luck cross the bar sooner or later. These are what Drafters and
    # Trialists would borrow.
    crowned = [e for e in entries if e.ending is Ending.CHALLENGER_WON]
    assert len(crowned) <= 1.4 * (1 - sure) * len(entries)
    assert all(e.ending in (Ending.SAME, Ending.LIMIT) or e.chance_better >= sure or e.chance_better <= 1 - sure for e in entries)


def test_the_report_lists_the_versions_and_the_playbook() -> None:
    result = run_simulation(only(load_settings(SETTINGS), 1000), seed=1)
    loop = result.by_start[1000].loop
    report = result.report.split("## Starting from 1,000 merchants", 1)[1]

    assert "#### Versions" in report and "#### Playbook" in report
    for version in loop.versions:
        assert f"| v{version.number} |" in report
    for entry in loop.playbook:
        assert entry.conclusion in report
    champion = loop.weekly_leaders[-1].champion
    assert f"Champion at the end of week {loop.weekly_leaders[-1].week}: v{champion}" in report


def test_while_a_test_runs_the_challenger_gets_its_share_of_idle_emails() -> None:
    settings = load_settings(SETTINGS)
    loop = loop_of(settings)
    sends = sum(e.challenger_sends for e in loop.playbook), sum(e.champion_sends + e.challenger_sends for e in loop.playbook)

    assert abs(sends[0] / sends[1] - settings.loop.challenger_share) < 0.03


def test_at_the_limit_the_version_ahead_stays_but_is_not_called_a_winner() -> None:
    settings = load_settings(SETTINGS)
    for keep_ahead in (True, False):
        loop = loop_of(dataclasses.replace(settings, loop=dataclasses.replace(settings.loop, keep_ahead_at_limit=keep_ahead)))
        at_limit = [e for e in loop.playbook if e.ending is Ending.LIMIT]
        assert at_limit
        champion = 0
        for entry in loop.playbook:
            assert entry.champion == champion  # each test is against the champion the last one left
            took_over = entry.ending is Ending.CHALLENGER_WON or (entry.ending is Ending.LIMIT and "kept, not proven" in entry.conclusion)
            champion = entry.challenger if took_over else entry.champion
            if entry.ending is Ending.LIMIT:
                ahead = entry.chance_better > 0.5
                assert ("kept, not proven" in entry.conclusion) == (keep_ahead and ahead and "fewer goal" not in entry.conclusion)
        assert loop.weekly_leaders[-1].champion == champion
