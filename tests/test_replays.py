import dataclasses
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from winback import Approach, Offer, RunResult, Segment, Settings, load_settings, run_simulation
from winback.cli import main

from conftest import SETTINGS, copy_settings, only

REPLAYS = 4


def only_1000(settings: Settings) -> Settings:
    return only(settings, 1000)


@pytest.fixture(scope="module")
def run() -> RunResult:
    return run_simulation(only_1000(load_settings(SETTINGS)), seed=1, replays=REPLAYS)


def percentile(values: list[float], p: float) -> float:
    """The p-th percentile by straight-line interpolation between the sorted values (worked by hand: the
    5th percentile of 0, 10, 20, 30 is 1.5)."""
    ordered = sorted(values)
    position = p / 100 * (len(ordered) - 1)
    below = int(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (position - below) * (ordered[above] - ordered[below])


def test_the_percentile_used_to_check_the_report_matches_a_worked_example() -> None:
    assert percentile([30, 0, 20, 10], 5) == pytest.approx(1.5)
    assert percentile([30, 0, 20, 10], 95) == pytest.approx(28.5)


def summary_part(report: str) -> str:
    return report.split("## Starting from", 1)[0]


def test_the_settings_ask_for_200_replays_at_both_starting_sizes() -> None:
    settings = load_settings(SETTINGS)

    assert settings.replays == 200
    assert settings.start_sizes == (1000, 1500)


def test_every_starting_size_is_replayed_with_different_luck_the_first_replay_being_the_seed_itself() -> None:
    settings = load_settings(SETTINGS)
    result = run_simulation(settings, seed=1, replays=3)
    single = run_simulation(settings, seed=1)

    for start in (1000, 1500):
        replays = result.replays[start]
        assert len(replays.seeds) == len(replays.stats) == 3
        assert replays.seeds[0] == 1 and len(set(replays.seeds)) == 3
        assert result.by_start[start].outcomes == single.by_start[start].outcomes
    lifts = [s.lifts[Segment.IDLE][Approach.AI_LOOP] for s in result.replays[1000].stats]
    assert len(set(lifts)) == 3


def test_each_replay_is_the_same_as_a_single_run_with_its_seed(run: RunResult) -> None:
    replays = run.replays[1000]

    for seed, stats in zip(replays.seeds, replays.stats):
        alone = run_simulation(only_1000(load_settings(SETTINGS)), seed=seed).by_start[1000]
        for segment in Segment:
            for approach in Approach:
                assert stats.lifts[segment][approach] == alone.outcomes[segment][approach].true_lift
        assert stats.revenue[Approach.AI_LOOP] == alone.outcomes[Segment.TRIALIST][Approach.AI_LOOP].first_month_revenue


def test_each_week_counts_only_results_known_by_then_and_the_last_week_is_the_true_lift(run: RunResult) -> None:
    # A result is known when its horizon closes: 8 days after entering Idle, 14 after publishing. The last
    # signups enter on day 91, so every result is known by day 105, the end of week 15.
    for stats in run.replays[1000].stats:
        for segment in Segment:
            for approach in Approach:
                weekly = stats.weekly[segment][approach]
                assert len(weekly) == 15
                assert weekly[-1] == pytest.approx(stats.lifts[segment][approach])
            assert all(v == 0 for v in stats.weekly[segment][Approach.NO_EMAIL])
        assert all(stats.weekly[segment][approach][0] == 0 for segment in Segment for approach in Approach)  # nothing known in week 1
    ai = [s.weekly[Segment.IDLE][Approach.AI_LOOP] for s in run.replays[1000].stats]
    assert any(week[1] != week[-1] for week in ai)  # early weeks are not just the final lift


def test_the_report_shows_average_lift_its_middle_90_percent_range_and_how_often_the_ai_loop_won(run: RunResult) -> None:
    replays = run.replays[1000]
    summary = summary_part(run.report)

    for segment in Segment:
        ai = [s.lifts[segment][Approach.AI_LOOP] * 100 for s in replays.stats]
        hand = [s.lifts[segment][Approach.HAND_WRITTEN] * 100 for s in replays.stats]
        wins = sum(a > h for a, h in zip(ai, hand))
        row = re.search(rf"\| {segment.value.title()} \| AI loop \| ([+-]\d+\.\d) \| ([+-]\d+\.\d) to ([+-]\d+\.\d) \| (\d+) ahead, (\d+) tied, of {REPLAYS} \|", summary)
        assert row, segment
        average, low, high, won, tied = float(row[1]), float(row[2]), float(row[3]), int(row[4]), int(row[5])
        assert tied == sum(a == h for a, h in zip(ai, hand))
        assert average == pytest.approx(statistics.fmean(ai), abs=0.05)
        assert (low, high) == pytest.approx((percentile(ai, 5), percentile(ai, 95)), abs=0.05)
        assert won == wins
        assert f"| {segment.value.title()} | Hand-written email | {statistics.fmean(hand):+.1f} |" in summary


def test_the_report_has_a_weekly_true_lift_chart_for_each_segment(run: RunResult) -> None:
    summary = summary_part(run.report)
    charts = re.findall(r"```mermaid\n(?:%%[^\n]*\n)?xychart-beta\n(.*?)```", summary, re.S)

    assert len(charts) == 3
    for segment, chart in zip(Segment, charts):
        assert segment.value.title() in chart
        lines = re.findall(r"line \[(.*?)\]", chart)
        assert len(lines) == 3  # no email (zero), hand-written, AI loop
        values = [[float(v) for v in line.split(",")] for line in lines]
        assert all(len(v) == 15 for v in values) and set(values[0]) == {0.0}
        ai_by_week_13 = statistics.fmean(s.weekly[segment][Approach.AI_LOOP][-1] for s in run.replays[1000].stats) * 100
        assert values[2][-1] == pytest.approx(ai_by_week_13, abs=0.01)
    assert "Grey: No email. Orange: Hand-written email. Blue: AI loop." in summary


def test_the_report_shows_average_trialist_first_month_revenue_per_approach(run: RunResult) -> None:
    summary = summary_part(run.report)

    for approach, label in ((Approach.NO_EMAIL, "No email"), (Approach.HAND_WRITTEN, "Hand-written email"), (Approach.AI_LOOP, "AI loop")):
        average = statistics.fmean(s.revenue[approach] for s in run.replays[1000].stats)
        assert f"| {label} | ${average:,.0f} |" in summary


def test_the_plain_english_summary_is_written_from_the_results() -> None:
    # An email that does nothing: nobody acts on one, and more trial days don't let anyone pay later. No
    # approach lifts anything, and the summary says so.
    settings = only_1000(load_settings(SETTINGS))
    nothing = {s: dataclasses.replace(b, act_rate=0.0) for s, b in settings.segments.items()}
    no_extension = dataclasses.replace(settings.offers, extra_trial_days=0.0)
    flat = run_simulation(dataclasses.replace(settings, segments=nothing, offers=no_extension), seed=1, replays=3).report
    # An AI loop that finds a far better Idle email and a far better Trialist offer.
    better = dataclasses.replace(settings, prewritten_subjects=(dataclasses.replace(settings.prewritten_subjects[0], quality=400), *settings.prewritten_subjects[1:]))
    better = dataclasses.replace(better, offers=dataclasses.replace(better.offers, pay_lift={**better.offers.pay_lift, Offer.EXTENSION: 3.0}))
    strong = run_simulation(better, seed=1, replays=3).report

    flat_summary = flat.split("## Summary", 1)[1].split("## ", 1)[0]
    strong_summary = strong.split("## Summary", 1)[1].split("## ", 1)[0]
    assert "From 1,000 merchants" in flat_summary and "From 1,000 merchants" in strong_summary
    assert "did better than the hand-written email in 0 of 3 segments" in flat_summary
    assert flat_summary.count("ahead in 0 of 3 replays and tied in 3") == 3  # a tie is not a win
    assert re.search(r"In Idle the AI loop did better: [+]\d+\.\d points against [+-]\d+\.\d", strong_summary)
    assert re.search(r"In Trialist the AI loop did better", strong_summary)
    assert "ahead from week" in strong_summary
    assert "No lessons are written yet" in strong_summary


def test_the_same_seed_gives_an_identical_report_across_every_replay() -> None:
    settings = only_1000(load_settings(SETTINGS))

    assert run_simulation(settings, seed=5, replays=3).report == run_simulation(settings, seed=5, replays=3).report


def test_the_command_runs_the_replays_from_the_settings_unless_told_otherwise(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    main(["--seed", "2", "--start", "1000", "--replays", "2", "--out", str(out)])

    assert "Across 2 replays" in out.read_text()
    assert out.read_text() == run_simulation(only_1000(load_settings(SETTINGS)), seed=2, replays=2).report


def test_the_week_the_summary_says_the_ai_loop_pulled_ahead_matches_its_chart() -> None:
    # A far better Idle subject: the AI loop pulls ahead in Idle and stays ahead.
    settings = only_1000(load_settings(SETTINGS))
    settings = dataclasses.replace(settings, prewritten_subjects=(dataclasses.replace(settings.prewritten_subjects[0], quality=400), *settings.prewritten_subjects[1:]))
    report = run_simulation(settings, seed=1, replays=3).report

    stated = re.search(r"In Idle the AI loop did better: .*?ahead from week (\d+) on average", report)
    chart_block = re.search(r"title \"Idle: cumulative true lift \(pts\)\".*?```", report, re.S)
    assert stated and chart_block
    week, chart = int(stated[1]), chart_block[0]
    _, hand, ai = ([float(v) for v in line.split(",")] for line in re.findall(r"line \[(.*?)\]", chart))
    assert all(a > h for a, h in zip(ai[week - 1 :], hand[week - 1 :]))
    assert week == 1 or ai[week - 2] <= hand[week - 2]


def test_the_summary_compares_the_ai_loops_edge_at_both_starting_sizes() -> None:
    result = run_simulation(load_settings(SETTINGS), seed=1, replays=2)

    def edge(start: int, segment: Segment) -> float:
        stats = result.replays[start].stats
        return statistics.fmean(s.lifts[segment][Approach.AI_LOOP] * 100 for s in stats) - statistics.fmean(s.lifts[segment][Approach.HAND_WRITTEN] * 100 for s in stats)

    moves = ", ".join(f"{segment.value.title()} {edge(1000, segment):+.1f} to {edge(1500, segment):+.1f}" for segment in Segment)
    assert f"Starting from 1,500 merchants instead of 1,000, the AI loop's edge over the hand-written email, in points, moved: {moves}." in result.report


def test_without_a_number_of_replays_the_command_replays_as_many_times_as_the_settings_say(tmp_path: Path) -> None:
    settings_file = copy_settings(tmp_path)
    settings_file.write_text(settings_file.read_text().replace("count = { value = 200,", "count = { value = 2,"))
    out = tmp_path / "report.md"

    main(["--settings", str(settings_file), "--start", "1000", "--out", str(out)])

    assert "## Across 2 replays" in out.read_text()


def test_the_summary_states_each_segments_average_lifts_from_the_replays(run: RunResult) -> None:
    summary = run.report.split("## Summary", 1)[1].split("## Across", 1)[0]

    for segment in Segment:
        ai = statistics.fmean(s.lifts[segment][Approach.AI_LOOP] * 100 for s in run.replays[1000].stats)
        hand = statistics.fmean(s.lifts[segment][Approach.HAND_WRITTEN] * 100 for s in run.replays[1000].stats)
        stated = re.escape(f": {ai:+.1f} points against {hand:+.1f} for the hand-written email")
        assert re.search(rf"In {segment.value.title()} the AI loop did (no )?better{stated}", summary), segment


def test_a_run_needs_at_least_one_replay() -> None:
    with pytest.raises(ValueError, match="at least one replay"):
        run_simulation(only_1000(load_settings(SETTINGS)), seed=1, replays=0)


def test_the_same_seed_gives_an_identical_report_in_separate_processes(tmp_path: Path) -> None:
    # Python's hash seed differs between processes; nothing in a report may depend on it.
    reports = []
    for hash_seed in ("1", "2"):
        out = tmp_path / f"report{hash_seed}.md"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        command = [sys.executable, "-m", "winback.cli", "--settings", str(SETTINGS), "--seed", "4", "--start", "1000", "--replays", "3", "--out", str(out)]
        subprocess.run(command, env=env, check=True, capture_output=True)
        reports.append(out.read_text())

    assert reports[0] == reports[1]
