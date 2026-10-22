from pathlib import Path

from winback import load_settings, run_simulation

SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"

# Worked by hand: 1,000 merchants, growth falling linearly from 10% (week 1)
# to 8% (week 13), each week's growth applied to the base as it stands.
WEEKLY_SIGNUPS_FROM_1000 = [100, 108, 117, 126, 135, 145, 156, 167, 178, 190, 202, 214, 227]


def test_new_signups_each_week_follow_the_growth_forecast() -> None:
    result = run_simulation(load_settings(SETTINGS), seed=1)

    assert result.weekly_signups == WEEKLY_SIGNUPS_FROM_1000


def test_existing_merchants_who_already_pay_are_counted_but_not_simulated() -> None:
    result = run_simulation(load_settings(SETTINGS), seed=1)

    assert result.existing_merchants == 1000
    assert result.already_paying == 150
    assert result.existing_simulated == 850


def test_new_signups_arrive_inside_their_week() -> None:
    result = run_simulation(load_settings(SETTINGS), seed=1)

    new = [m for m in result.merchants if not m.existing]
    assert len(new) == sum(WEEKLY_SIGNUPS_FROM_1000)
    for week, count in enumerate(WEEKLY_SIGNUPS_FROM_1000):
        in_week = [m for m in new if 7 * week <= m.arrival_day < 7 * (week + 1)]
        assert len(in_week) == count


def test_the_seed_decides_arrival_times_but_not_weekly_counts() -> None:
    settings = load_settings(SETTINGS)
    first, again, other = run_simulation(settings, seed=1), run_simulation(settings, seed=1), run_simulation(settings, seed=2)

    assert [m.arrival_day for m in first.merchants] == [m.arrival_day for m in again.merchants]
    assert [m.arrival_day for m in first.merchants] != [m.arrival_day for m in other.merchants]
    assert first.weekly_signups == other.weekly_signups


def test_the_report_shows_merchants_and_weekly_signups() -> None:
    report = run_simulation(load_settings(SETTINGS), seed=1).report

    assert "Merchants today: 1,000" in report
    assert "Already paying (not simulated): 150" in report
    assert "| 1 | 100 |" in report
    assert "| 13 | 227 |" in report
    assert "| Total | 2,065 |" in report


def test_the_report_labels_every_placeholder() -> None:
    report = run_simulation(load_settings(SETTINGS), seed=1).report

    placeholders = report.split("## Placeholders", 1)[1]
    assert "Share of today's merchants who already pay" in placeholders
    assert "Merchants today (founder's figure)" not in placeholders


def test_the_same_seed_gives_an_identical_report() -> None:
    settings = load_settings(SETTINGS)

    assert run_simulation(settings, seed=7).report == run_simulation(settings, seed=7).report


def test_one_command_writes_the_report_and_can_start_from_1500(tmp_path: Path) -> None:
    from winback.cli import main

    out = tmp_path / "report.md"
    main(["--settings", str(SETTINGS), "--start", "1500", "--seed", "3", "--out", str(out)])

    report = out.read_text()
    assert "Merchants today: 1,500" in report
    assert "Already paying (not simulated): 225" in report
    # Worked by hand: 1,500 x 10% = 150; then 1,650 x 9.83% = 162; then 1,812 x 9.67% = 175.
    assert "| 1 | 150 |" in report and "| 2 | 162 |" in report and "| 3 | 175 |" in report
