"""The spending cap (#14): spend is summed from what each call reports, a warning at one limit, no live calls
past the other, and every replay still finishes on the variants already written and judged."""

import dataclasses

from winback import Settings, load_settings, run_simulation
from winback.copywriter import AiCopywriter, Spend
from winback.settings import Email

from conftest import SETTINGS, only
from test_copywriter import FakeJudge, FakeWriter

COST_PER_CALL = 1.0  # dollars, as the fake connector reports it


class CostedWriter(FakeWriter):
    """A fake writer that reports a cost for each call, as OpenRouter does, and notes the spend before it."""

    def __init__(self, spend: Spend) -> None:
        super().__init__()
        self.spend, self.spend_before = spend, list[float]()

    def write(self, slot: str, champion: Email, conclusions: list[str], tried: list[str], feedback: list[str]) -> tuple[str, str, str]:
        self.spend_before.append(self.spend.cost)
        self.spend.cost += COST_PER_CALL
        return super().write(slot, champion, conclusions, tried, feedback)


class CostedJudge(FakeJudge):
    def __init__(self, spend: Spend) -> None:
        super().__init__()
        self.spend, self.spend_before = spend, list[float]()

    def rate(self, slot: str, text: str, cta: str) -> float:
        self.spend_before.append(self.spend.cost)
        self.spend.cost += COST_PER_CALL
        return super().rate(slot, text, cta)


def with_limits(warning: float, stop: float) -> Settings:
    settings = only(load_settings(SETTINGS), 1000)
    return dataclasses.replace(settings, writer=dataclasses.replace(settings.writer, spend_warning=warning, spend_stop=stop))


def costed(settings: Settings) -> tuple[AiCopywriter, CostedWriter, CostedJudge, list[str]]:
    spend, warnings = Spend(), list[str]()
    writer, judge = CostedWriter(spend), CostedJudge(spend)
    return AiCopywriter(settings, writer, judge, spend, warn=warnings.append), writer, judge, warnings


def test_both_limits_are_in_settings_at_5_and_10_dollars() -> None:
    settings = load_settings(SETTINGS)

    assert (settings.writer.spend_warning, settings.writer.spend_stop) == (5.0, 10.0)
    assert {"writer.spend_warning", "writer.spend_stop"} <= {e.key for e in settings.entries}


def test_the_cap_stops_live_calls_at_the_limit_and_every_replay_still_finishes() -> None:
    settings = with_limits(warning=3, stop=6)
    copywriter, writer, judge, _ = costed(settings)

    result = run_simulation(settings, seed=1, replays=3, copywriter=copywriter)

    calls = writer.spend_before + judge.spend_before
    assert calls and all(before < 6 for before in calls)  # no live call once spend reached the stop limit
    assert copywriter.spend.cost == len(calls) * COST_PER_CALL  # spend is summed from what each call reported
    assert len(result.replays[1000].stats) == 3  # every replay finished
    assert result.by_start[1000].loop.versions  # the loop still ran on what was already written
    assert "Spend reached the $6.00 stop" in result.report
    assert "1 of 3 replays made live calls; 2 reused variants already written and judged in this run." in result.report


def test_a_warning_is_given_once_when_spend_passes_the_warning_limit_and_the_run_keeps_going() -> None:
    settings = with_limits(warning=3, stop=100)
    copywriter, writer, judge, warnings = costed(settings)

    result = run_simulation(settings, seed=1, replays=2, copywriter=copywriter)

    assert len(warnings) == 1 and "$3.00" in warnings[0]
    assert copywriter.spend.cost > 4  # calls went on past the warning
    assert warnings[0] in result.report


def test_under_both_limits_the_report_states_the_spend_and_no_warning() -> None:
    settings = with_limits(warning=500, stop=1000)
    copywriter, _, _, warnings = costed(settings)

    report = run_simulation(settings, seed=1, replays=2, copywriter=copywriter).report

    assert warnings == []
    assert f"${copywriter.spend.cost:,.2f} reported by OpenRouter" in report
    assert "Spend passed" not in report and "Spend reached" not in report
    assert "1 of 2 replays made live calls; 1 reused variants already written and judged in this run." in report
