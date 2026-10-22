import dataclasses
from pathlib import Path

import pytest

from winback import Approach, RunResult, Segment, Settings, load_settings, run_simulation

SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"

# Worked by hand: 1,000 merchants, growth falling linearly from 10% (week 1)
# to 8% (week 13), each week's growth applied to the base as it stands.
WEEKLY_SIGNUPS_FROM_1000 = [100, 108, 117, 126, 135, 145, 156, 167, 178, 190, 202, 214, 227]


def with_segments(
    idle: dict[str, float] | None = None,
    drafter: dict[str, float] | None = None,
    trialist: dict[str, float] | None = None,
) -> Settings:
    settings = load_settings(SETTINGS)
    changes = {Segment.IDLE: idle, Segment.DRAFTER: drafter, Segment.TRIALIST: trialist}
    segments = {s: dataclasses.replace(b, **(changes[s] or {})) for s, b in settings.segments.items()}
    return dataclasses.replace(settings, segments=segments)


def with_idle(**changes: float) -> Settings:
    return with_segments(idle=changes)


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


# Idle holds every new signup plus the existing merchants who are Idle today (50% of 1,000).
IDLE_FROM_1000 = sum(WEEKLY_SIGNUPS_FROM_1000) + 500


def test_every_merchant_starting_in_idle_is_counted(run: RunResult) -> None:
    idle = run.by_start[1000].idle

    assert idle[Approach.NO_EMAIL].counted == idle[Approach.HAND_WRITTEN].counted == IDLE_FROM_1000


def test_an_email_that_does_nothing_has_exactly_zero_true_lift() -> None:
    idle = run_simulation(with_idle(act_rate=0.0), seed=1).by_start[1000].idle

    assert idle[Approach.HAND_WRITTEN].reached == idle[Approach.NO_EMAIL].reached
    assert idle[Approach.HAND_WRITTEN].true_lift == 0.0


def test_merchants_who_start_a_draft_before_the_email_is_due_are_skipped() -> None:
    everyone_drafts_fast = with_idle(organic_share=1.0, organic_mean_days=0.01)
    email = run_simulation(everyone_drafts_fast, seed=1).by_start[1000].idle[Approach.HAND_WRITTEN]

    assert email.emails.sent == 0
    assert email.emails.skipped == email.counted


def test_when_nobody_drafts_alone_everyone_gets_the_email_and_it_lifts_drafts() -> None:
    idle = run_simulation(with_idle(organic_share=0.0), seed=1).by_start[1000].idle

    assert idle[Approach.HAND_WRITTEN].emails.skipped == 0
    assert idle[Approach.HAND_WRITTEN].emails.sent == idle[Approach.HAND_WRITTEN].counted
    assert idle[Approach.NO_EMAIL].reached == 0
    assert idle[Approach.HAND_WRITTEN].true_lift > 0


def test_the_report_shows_idle_results_and_the_first_draft_that_was_sent(run: RunResult) -> None:
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]

    assert "### Idle: start a draft" in from_1000
    assert "| No email | 2,565 |" in from_1000
    assert "| Hand-written email (your first draft) | 2,565 |" in from_1000
    assert "Your new store is one clone away" in run.report
    assert "Clone a store to start from, then make every page yours with the section builder." in run.report
    assert "[Start my first draft]" in run.report


# A world where nobody drafts on their own and everyone who gets the email reads it,
# clicks and starts a draft almost at once. Every outcome below is worked out by hand.
CERTAIN_EMAIL = dict(organic_share=0.0, read_rate=1.0, click_rate=1.0, act_rate=1.0, response_mean_days=0.001)


def test_an_email_that_arrives_after_the_horizon_cannot_lift_drafts() -> None:
    idle = run_simulation(with_idle(**CERTAIN_EMAIL, hand_written_after_days=9), seed=1).by_start[1000].idle

    assert idle[Approach.HAND_WRITTEN].true_lift == 0.0


def test_reading_and_clicking_are_separate_chances_set_in_settings() -> None:
    # Worked by hand: 35% read x 60% click x 100% start a draft = 21% of 2,065 merchants.
    # Chance alone moves this by under 3 points (three standard deviations).
    settings = with_idle(**{**CERTAIN_EMAIL, "read_rate": 0.35, "click_rate": 0.6})
    lift = run_simulation(settings, seed=1).by_start[1000].idle[Approach.HAND_WRITTEN].true_lift

    assert 0.18 < lift < 0.24


def test_a_slow_response_lands_after_the_horizon() -> None:
    # Worked by hand: with 1,000 days on average between click and draft, only
    # 1 - e^(-6/1000) = 0.6% start a draft within the 6 days left before the horizon.
    settings = with_idle(**{**CERTAIN_EMAIL, "response_mean_days": 1000})
    lift = run_simulation(settings, seed=1).by_start[1000].idle[Approach.HAND_WRITTEN].true_lift

    assert lift < 0.02


def test_an_email_never_makes_a_merchant_draft_later_than_they_would_have() -> None:
    # Half would draft on their own (often after the email); the email prompts drafts far too late to count.
    settings = with_idle(**{**CERTAIN_EMAIL, "organic_share": 0.5, "organic_mean_days": 3, "response_mean_days": 1000})
    idle = run_simulation(settings, seed=1).by_start[1000].idle

    assert idle[Approach.HAND_WRITTEN].reached >= idle[Approach.NO_EMAIL].reached


def test_a_merchant_signing_up_at_the_end_of_week_13_still_gets_its_full_window() -> None:
    # A 20-day Idle horizon, longer than the old fixed 14-day run-out, and an email on day 15 that
    # makes everyone draft at once. Only if the run lasts until the last window closes do merchants
    # who sign up at the end of week 13 get their day-15 email, so every Idle merchant drafts in time.
    settings = with_idle(**CERTAIN_EMAIL, horizon_days=20, hand_written_after_days=15)
    email = run_simulation(settings, seed=1).by_start[1000].idle[Approach.HAND_WRITTEN]

    assert email.counted == IDLE_FROM_1000
    assert email.reached == email.counted


def test_the_calendar_handles_every_merchants_events_in_date_order(run: RunResult) -> None:
    for approach in Approach:
        days = run.by_start[1000].event_days[approach]
        assert len(days) > IDLE_FROM_1000
        assert all(earlier <= later for earlier, later in zip(days, days[1:]))


def test_the_report_states_idle_results_in_percentage_points() -> None:
    report = run_simulation(with_idle(**CERTAIN_EMAIL), seed=1).report

    assert "| No email | 2,565 | 0.0% | reference | 0 | 0 |" in report
    assert "| Hand-written email (your first draft) | 2,565 | 100.0% | +100.0 | 2,565 | 0 |" in report


def test_the_report_shows_the_send_day_from_settings() -> None:
    report = run_simulation(with_idle(hand_written_after_days=3), seed=1).report

    assert "Sent 3 days after entering Idle (signup, for new merchants)." in report


def test_the_command_can_run_a_single_starting_size(tmp_path: Path) -> None:
    from winback.cli import main

    out = tmp_path / "report.md"
    main(["--settings", str(SETTINGS), "--start", "1500", "--out", str(out)])

    report = out.read_text()
    assert "## Starting from 1,500 merchants" in report
    assert "## Starting from 1,000 merchants" not in report


def test_a_number_written_without_its_placeholder_flag_is_refused(tmp_path: Path) -> None:
    broken = SETTINGS.read_text().replace(
        'weeks = { value = 13, placeholder = false, note = "Length of the simulation in weeks." }', "weeks = 13"
    )
    (tmp_path / "settings.toml").write_text(broken)
    (tmp_path / "first_drafts.toml").write_text((SETTINGS.parent / "first_drafts.toml").read_text())

    with pytest.raises(ValueError, match="growth.weeks"):
        load_settings(tmp_path / "settings.toml")


def test_existing_merchants_start_in_their_segment_spread_over_two_weeks(run: RunResult) -> None:
    existing = [m for m in run.by_start[1000].merchants if m.existing]

    assert [sum(m.start_segment is s for m in existing) for s in (Segment.IDLE, Segment.DRAFTER, Segment.TRIALIST)] == [500, 250, 100]
    assert all(0 <= m.arrival_day < 14 for m in existing)
    assert max(m.arrival_day for m in existing) > 10


LIFECYCLE = [Segment.IDLE, Segment.DRAFTER, Segment.TRIALIST]


def test_merchants_move_through_the_lifecycle_in_order_one_segment_at_a_time(run: RunResult) -> None:
    journeys = run.by_start[1000].journeys[Approach.HAND_WRITTEN]
    reached_paid = 0
    for journey in journeys:
        order = [LIFECYCLE.index(stay.segment) for stay in journey.stays]
        assert order == list(range(order[0], order[0] + len(order)))
        for before, after in zip(journey.stays, journey.stays[1:]):
            assert before.left is not None and before.left == after.entered
        if journey.paid_at is not None:
            assert journey.stays[-1].segment is Segment.TRIALIST and journey.stays[-1].left == journey.paid_at
            reached_paid += 1
    assert reached_paid > 0


def test_no_merchant_gets_more_than_one_email_per_segment(run: RunResult) -> None:
    for journey in run.by_start[1000].journeys[Approach.HAND_WRITTEN]:
        segments_emailed = [stay.segment for stay in journey.stays if stay.email_sent_at is not None]
        assert len(segments_emailed) == len(set(segments_emailed))


def test_no_merchant_gets_two_emails_less_than_48_hours_apart() -> None:
    # Every Idle merchant drafts right after the Idle email, and the Drafter email would be
    # due only 6 hours later, so the 48-hour gap has to hold it back.
    settings = with_segments(idle=CERTAIN_EMAIL, drafter={"hand_written_after_days": 0.25})
    journeys = run_simulation(settings, seed=1).by_start[1000].journeys[Approach.HAND_WRITTEN]

    held_back = 0
    for journey in journeys:
        sent = [stay.email_sent_at for stay in journey.stays if stay.email_sent_at is not None]
        assert all(later - earlier >= 2 - 1e-9 for earlier, later in zip(sent, sent[1:]))  # allow float rounding
        held_back += any(s.segment is Segment.DRAFTER and s.email_sent_at is not None and s.email_sent_at > s.entered + 0.25 for s in journey.stays)
    assert held_back > 0


def test_drafters_who_publish_before_their_email_is_due_are_skipped() -> None:
    settings = with_segments(drafter={"organic_share": 1.0, "organic_mean_days": 0.01})
    drafters = run_simulation(settings, seed=1).by_start[1000].traffic[Approach.HAND_WRITTEN][Segment.DRAFTER]

    assert drafters.entered > 250
    assert drafters.emails.sent == 0
    assert drafters.emails.skipped == drafters.entered


def test_the_report_shows_each_segments_traffic_and_every_first_draft() -> None:
    settings = with_segments(drafter={"organic_share": 1.0, "organic_mean_days": 0.01})
    run = run_simulation(settings, seed=1)
    drafters = run.by_start[1000].traffic[Approach.HAND_WRITTEN][Segment.DRAFTER]

    assert "### Segments with your first drafts" in run.report
    assert f"| Drafter | {drafters.entered:,} | 0 | {drafters.entered:,} |" in run.report
    assert "{store_name} is ready to go live" in run.report
    assert "You won't pay anything until the trial ends." in run.report
    assert "[Publish my store]" in run.report
    assert "Keep {store_name} live after your trial" in run.report
    assert "[Keep my store live]" in run.report


def test_trialists_only_pay_inside_their_seven_day_trial() -> None:
    # Slow payers and slow responders: many would pay after day 7 if the trial allowed it.
    settings = with_segments(trialist={**CERTAIN_EMAIL, "organic_share": 0.5, "organic_mean_days": 20, "response_mean_days": 20})
    for approach in Approach:
        trialist_stays = [
            stay for j in run_simulation(settings, seed=1).by_start[1000].journeys[approach]
            for stay in j.stays if stay.segment is Segment.TRIALIST and stay.left is not None
        ]
        assert trialist_stays
        assert all(stay.left - stay.entered <= 7 for stay in trialist_stays if stay.left is not None)


def test_a_trialist_email_due_after_the_trial_has_ended_is_skipped() -> None:
    settings = with_segments(trialist={"hand_written_after_days": 8})
    trialists = run_simulation(settings, seed=1).by_start[1000].traffic[Approach.HAND_WRITTEN][Segment.TRIALIST]

    assert trialists.emails.sent == 0
    assert trialists.emails.skipped == trialists.entered > 100


def test_a_merchants_luck_in_one_segment_does_not_decide_the_next() -> None:
    # 30% draft on their own and 30% of Drafters publish on their own, both within hours.
    # Worked by hand: with independent luck, about 30% of organic drafters also publish.
    fast = {"organic_share": 0.3, "organic_mean_days": 0.01}
    journeys = run_simulation(with_segments(idle=fast, drafter=fast), seed=1).by_start[1000].journeys[Approach.NO_EMAIL]
    drafted = [j for j in journeys if j.stays[0].segment is Segment.IDLE and len(j.stays) > 1]
    published = [j for j in drafted if len(j.stays) > 2]

    assert 0.25 < len(published) / len(drafted) < 0.35


def test_about_a_fifth_of_trialists_pay_inside_the_trial_with_no_email() -> None:
    # The spec's placeholder: about 20% of Trialists pay before the trial ends with no email.
    # 10,000 merchants, 85% of them existing Trialists, so chance moves the share by under 1.5 points.
    settings = dataclasses.replace(
        load_settings(SETTINGS),
        start_sizes=(10_000,),
        already_paying_share=0.0,
        existing_shares={Segment.IDLE: 0.15, Segment.DRAFTER: 0.0, Segment.TRIALIST: 0.85},
    )
    journeys = run_simulation(settings, seed=1).by_start[10_000].journeys[Approach.NO_EMAIL]
    trialists = [j for j in journeys if j.merchant.start_segment is Segment.TRIALIST]
    paid = sum(j.paid_at is not None for j in trialists)

    assert 0.185 < paid / len(trialists) < 0.215


def test_a_goal_action_from_an_earlier_segment_cannot_end_a_later_one() -> None:
    # Everyone would draft on their own around day 5, but the email gets them drafting within hours.
    # Every Drafter would publish on their own only after about a billion days, and the Drafter email
    # can't prompt it, so no Drafter stay may end in the run. A leftover "would have drafted on day 5"
    # from Idle must not count as publishing.
    settings = with_segments(
        idle={**CERTAIN_EMAIL, "organic_share": 1.0, "organic_mean_days": 5.0},
        drafter={"organic_share": 1.0, "organic_mean_days": 1e9, "act_rate": 0.0},
    )
    journeys = run_simulation(settings, seed=1).by_start[1000].journeys[Approach.HAND_WRITTEN]
    drafter_stays = [s for j in journeys for s in j.stays if s.segment is Segment.DRAFTER]

    assert len(drafter_stays) > 1000
    assert all(stay.left is None for stay in drafter_stays)
