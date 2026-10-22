import dataclasses
from pathlib import Path

import pytest

from winback import RunResult, load_settings, run_simulation

SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"

# Worked by hand: 1,000 merchants, growth falling linearly from 10% (week 1)
# to 8% (week 13), each week's growth applied to the base as it stands.
WEEKLY_SIGNUPS_FROM_1000 = [100, 108, 117, 126, 135, 145, 156, 167, 178, 190, 202, 214, 227]


@pytest.fixture
def run() -> RunResult:
    return run_simulation(load_settings(SETTINGS), seed=1)


def test_new_signups_each_week_follow_the_growth_forecast(run: RunResult) -> None:
    assert run.by_start[1000].weekly_signups == WEEKLY_SIGNUPS_FROM_1000


def test_the_same_run_also_starts_from_1500(run: RunResult) -> None:
    # Worked by hand: 1,500 x 10% = 150; then 1,650 x 9.83% = 162; then 1,812 x 9.67% = 175.
    assert run.by_start[1500].weekly_signups[:3] == [150, 162, 175]


def test_existing_merchants_who_already_pay_are_counted_but_not_simulated(run: RunResult) -> None:
    start = run.by_start[1000]

    assert (start.existing_merchants, start.already_paying, start.existing_simulated) == (1000, 150, 850)
    assert sum(m.existing for m in start.merchants) == 850


def test_new_signups_arrive_inside_their_week(run: RunResult) -> None:
    new = [m for m in run.by_start[1000].merchants if not m.existing]
    assert len(new) == sum(WEEKLY_SIGNUPS_FROM_1000)
    for week, count in enumerate(WEEKLY_SIGNUPS_FROM_1000):
        in_week = [m for m in new if 7 * week <= m.arrival_day < 7 * (week + 1)]
        assert len(in_week) == count


def test_the_seed_decides_arrival_times_but_not_weekly_counts() -> None:
    settings = load_settings(SETTINGS)
    first, again, other = (run_simulation(settings, seed=s).by_start[1000] for s in (1, 1, 2))

    assert [m.arrival_day for m in first.merchants] == [m.arrival_day for m in again.merchants]
    assert [m.arrival_day for m in first.merchants] != [m.arrival_day for m in other.merchants]
    assert first.weekly_signups == other.weekly_signups


def test_a_signups_arrival_does_not_shift_when_existing_merchants_change() -> None:
    settings = load_settings(SETTINGS)
    more_paying = dataclasses.replace(settings, already_paying_share=0.3)

    first_signup = next(m for m in run_simulation(settings, seed=1).by_start[1000].merchants if not m.existing)
    same_signup = next(m for m in run_simulation(more_paying, seed=1).by_start[1000].merchants if not m.existing)
    assert first_signup.arrival_day == same_signup.arrival_day


def test_the_report_shows_both_starting_sizes_and_their_weekly_signups(run: RunResult) -> None:
    after_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1]
    from_1000, from_1500 = after_1000.split("## Starting from 1,500 merchants", 1)

    assert "Merchants today: 1,000" in from_1000
    assert "Already paying (not simulated): 150" in from_1000
    assert "| 1 | 100 |" in from_1000 and "| 13 | 227 |" in from_1000 and "| Total | 2,065 |" in from_1000
    assert "Merchants today: 1,500" in from_1500
    assert "Already paying (not simulated): 225" in from_1500
    assert "| 1 | 150 |" in from_1500


def test_the_report_labels_every_placeholder(run: RunResult) -> None:
    placeholders = run.report.split("## Placeholders", 1)[1]

    assert "Share of existing merchants who already pay" in placeholders
    assert "Merchants today (founder's figure)" not in placeholders


def test_the_same_seed_gives_an_identical_report() -> None:
    settings = load_settings(SETTINGS)

    assert run_simulation(settings, seed=7).report == run_simulation(settings, seed=7).report


def test_one_command_writes_the_report(tmp_path: Path) -> None:
    from winback.cli import main

    out = tmp_path / "report.md"
    main(["--settings", str(SETTINGS), "--seed", "3", "--out", str(out)])

    report = out.read_text()
    assert "## Starting from 1,000 merchants" in report and "## Starting from 1,500 merchants" in report


def test_every_new_signup_is_judged_in_idle(run: RunResult) -> None:
    idle = run.by_start[1000].idle

    assert idle["no_email"].judged == idle["hand_written"].judged == sum(WEEKLY_SIGNUPS_FROM_1000)


def test_an_email_that_does_nothing_has_exactly_zero_true_lift() -> None:
    no_effect = dataclasses.replace(load_settings(SETTINGS), idle_act_rate=0.0)
    idle = run_simulation(no_effect, seed=1).by_start[1000].idle

    assert idle["hand_written"].reached == idle["no_email"].reached
    assert idle["hand_written"].true_lift == 0.0


def test_merchants_who_start_a_draft_before_the_email_is_due_are_skipped() -> None:
    everyone_drafts_fast = dataclasses.replace(load_settings(SETTINGS), idle_organic_share=1.0, idle_organic_mean_days=0.01)
    email = run_simulation(everyone_drafts_fast, seed=1).by_start[1000].idle["hand_written"]

    assert email.sent == 0
    assert email.skipped == email.judged


def test_when_nobody_drafts_alone_everyone_gets_the_email_and_it_lifts_drafts() -> None:
    nobody_drafts_alone = dataclasses.replace(load_settings(SETTINGS), idle_organic_share=0.0)
    idle = run_simulation(nobody_drafts_alone, seed=1).by_start[1000].idle

    assert idle["hand_written"].skipped == 0
    assert idle["hand_written"].sent == idle["hand_written"].judged
    assert idle["no_email"].reached == 0
    assert idle["hand_written"].true_lift > 0


def test_the_report_shows_idle_results_and_the_first_draft_that_was_sent(run: RunResult) -> None:
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]

    assert "### Idle: start a draft" in from_1000
    assert "| No email | 2,065 |" in from_1000
    assert "| Hand-written email (your first draft) | 2,065 |" in from_1000
    assert "Your new store is one clone away" in run.report
    assert "Clone a store to start from, then make every page yours with the section builder." in run.report
    assert "[Start my first draft]" in run.report
