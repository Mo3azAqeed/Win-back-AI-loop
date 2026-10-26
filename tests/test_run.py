import dataclasses
from pathlib import Path

import pytest

from winback import Approach, Offer, RunResult, Segment, Settings, load_settings, run_simulation
from winback.lifecycle import EmailFate, Journey

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
    assert "The hidden quality of each of the stand-in writer's 8 subjects and 8 bodies" in placeholders


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


def test_every_merchant_starting_in_idle_is_counted_once_emailed_or_held_out(run: RunResult) -> None:
    idle = run.by_start[1000].outcomes[Segment.IDLE]
    held_out = run.by_start[1000].baselines[Segment.IDLE]

    assert idle[Approach.NO_EMAIL].counted == idle[Approach.HAND_WRITTEN].counted
    assert idle[Approach.HAND_WRITTEN].counted + held_out.counted == IDLE_FROM_1000


def test_an_email_that_does_nothing_has_exactly_zero_true_lift() -> None:
    idle = run_simulation(with_idle(act_rate=0.0), seed=1).by_start[1000].outcomes[Segment.IDLE]

    assert idle[Approach.HAND_WRITTEN].reached == idle[Approach.NO_EMAIL].reached
    assert idle[Approach.HAND_WRITTEN].true_lift == 0.0


def test_merchants_who_start_a_draft_before_the_email_is_due_are_skipped() -> None:
    everyone_drafts_fast = with_idle(organic_share=1.0, organic_mean_days=0.01)
    email = run_simulation(everyone_drafts_fast, seed=1).by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN]

    assert email.emails.sent == 0
    assert email.emails.skipped == email.counted


def test_when_nobody_drafts_alone_everyone_gets_the_email_and_it_lifts_drafts() -> None:
    idle = run_simulation(with_idle(organic_share=0.0), seed=1).by_start[1000].outcomes[Segment.IDLE]

    assert idle[Approach.HAND_WRITTEN].emails.skipped == 0
    assert idle[Approach.HAND_WRITTEN].emails.sent == idle[Approach.HAND_WRITTEN].counted
    assert idle[Approach.NO_EMAIL].reached == 0
    assert idle[Approach.HAND_WRITTEN].true_lift > 0


def test_the_report_shows_idle_results_and_the_first_draft_that_was_sent(run: RunResult) -> None:
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]

    assert "### Idle: start a draft" in from_1000
    emailed = run.by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN].counted
    assert f"| No email | {emailed:,} |" in from_1000
    assert f"| Hand-written email (your first draft) | {emailed:,} |" in from_1000
    assert "Your new store is one clone away" in run.report
    assert "Clone a store to start from, then make every page yours with the section builder." in run.report
    assert "[Start my first draft]" in run.report


# A world where nobody drafts on their own and everyone who gets the email reads it,
# clicks and starts a draft almost at once. Every outcome below is worked out by hand.
CERTAIN_EMAIL = dict(organic_share=0.0, read_rate=1.0, click_rate=1.0, act_rate=1.0, response_mean_days=0.001)


def test_an_email_that_arrives_after_the_horizon_cannot_lift_drafts() -> None:
    idle = run_simulation(with_idle(**CERTAIN_EMAIL, hand_written_after_days=9), seed=1).by_start[1000].outcomes[Segment.IDLE]

    assert idle[Approach.HAND_WRITTEN].true_lift == 0.0


def test_reading_and_clicking_are_separate_chances_set_in_settings() -> None:
    # Worked by hand: 35% read x 60% click x 100% start a draft = 21% of 2,065 merchants.
    # Chance alone moves this by under 3 points (three standard deviations).
    settings = with_idle(**{**CERTAIN_EMAIL, "read_rate": 0.35, "click_rate": 0.6})
    lift = run_simulation(settings, seed=1).by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN].true_lift

    assert 0.18 < lift < 0.24


def test_a_slow_response_lands_after_the_horizon() -> None:
    # Worked by hand: with 1,000 days on average between click and draft, only
    # 1 - e^(-6/1000) = 0.6% start a draft within the 6 days left before the horizon.
    settings = with_idle(**{**CERTAIN_EMAIL, "response_mean_days": 1000})
    lift = run_simulation(settings, seed=1).by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN].true_lift

    assert lift < 0.02


def test_an_email_never_makes_a_merchant_draft_later_than_they_would_have() -> None:
    # Half would draft on their own (often after the email); the email prompts drafts far too late to count.
    settings = with_idle(**{**CERTAIN_EMAIL, "organic_share": 0.5, "organic_mean_days": 3, "response_mean_days": 1000})
    idle = run_simulation(settings, seed=1).by_start[1000].outcomes[Segment.IDLE]

    assert idle[Approach.HAND_WRITTEN].reached >= idle[Approach.NO_EMAIL].reached


def test_a_merchant_signing_up_at_the_end_of_week_13_still_gets_its_full_horizon() -> None:
    # A 20-day Idle horizon, longer than the old fixed 14-day run-out, and an email on day 15 that
    # makes everyone draft at once. Only if the run lasts until the last horizon closes do merchants
    # who sign up at the end of week 13 get their day-15 email, so every Idle merchant drafts in time.
    settings = with_idle(**CERTAIN_EMAIL, horizon_days=20, hand_written_after_days=15)
    start = run_simulation(settings, seed=1).by_start[1000]
    email = start.outcomes[Segment.IDLE][Approach.HAND_WRITTEN]

    assert email.counted + start.baselines[Segment.IDLE].counted == IDLE_FROM_1000
    assert email.reached == email.counted


def test_the_calendar_handles_every_merchants_events_in_date_order(run: RunResult) -> None:
    for approach in Approach:
        days = run.by_start[1000].event_days[approach]
        assert len(days) > IDLE_FROM_1000
        assert all(earlier <= later for earlier, later in zip(days, days[1:]))


def test_the_report_states_idle_results_in_percentage_points() -> None:
    run = run_simulation(with_idle(**CERTAIN_EMAIL), seed=1)
    emailed = run.by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN].counted

    assert f"| No email | {emailed:,} | 0.0% | reference |" in run.report
    assert f"| Hand-written email (your first draft) | {emailed:,} | 100.0% | +100.0 |" in run.report


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
    for companion in ("first_drafts.toml", "prewritten.toml"):
        (tmp_path / companion).write_text((SETTINGS.parent / companion).read_text())

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
    drafters = run_simulation(settings, seed=1).by_start[1000].outcomes[Segment.DRAFTER][Approach.HAND_WRITTEN]

    assert drafters.counted > 250
    assert drafters.emails.sent == 0
    assert drafters.emails.skipped == drafters.counted


def test_the_report_shows_each_segments_results_and_every_first_draft() -> None:
    settings = with_segments(drafter={"organic_share": 1.0, "organic_mean_days": 0.01})
    run = run_simulation(settings, seed=1)
    drafters = run.by_start[1000].outcomes[Segment.DRAFTER][Approach.HAND_WRITTEN]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]

    assert "### Drafter: publish" in from_1000 and "### Trialist: pay" in from_1000
    assert f"| Hand-written email (your first draft) | {drafters.counted:,} | 100.0% | +0.0 |" in from_1000
    # The emails table counts every Drafter email, including those to merchants pushed here by an Idle email.
    pushed = run.by_start[1000].pushed[Segment.DRAFTER][Approach.HAND_WRITTEN]
    assert f"| Hand-written email (your first draft) | 0 | {drafters.counted + pushed.counted:,} | 0 | 0 |" in from_1000
    assert "{store_name} is ready to go live" in run.report
    assert "You won't pay anything until the trial ends." in run.report
    assert "[Publish my store]" in run.report
    assert "Keep {store_name} live after your trial" in run.report
    assert "[Keep my store live]" in run.report


def test_trialists_only_pay_inside_their_seven_day_trial() -> None:
    # Slow payers and slow responders: many would pay after day 7 if the trial allowed it. An AI loop
    # email offering more trial days is the exception (tests/test_offers.py).
    settings = with_segments(trialist={**CERTAIN_EMAIL, "organic_share": 0.5, "organic_mean_days": 20, "response_mean_days": 20})
    for approach in Approach:
        trialist_stays = [
            stay for j in run_simulation(settings, seed=1).by_start[1000].journeys[approach]
            for stay in j.stays if stay.segment is Segment.TRIALIST and stay.left is not None
            and not (stay.offer is Offer.EXTENSION and stay.email is EmailFate.SENT)
        ]
        assert trialist_stays
        assert all(stay.left - stay.entered <= 7 for stay in trialist_stays if stay.left is not None)


def test_a_trialist_email_due_after_the_trial_has_ended_is_skipped_real_or_ghost() -> None:
    settings = with_segments(trialist={"hand_written_after_days": 8})
    start = run_simulation(settings, seed=1).by_start[1000]
    trialists, held_out = start.outcomes[Segment.TRIALIST][Approach.HAND_WRITTEN], start.baselines[Segment.TRIALIST]

    assert trialists.emails.sent == held_out.emails.sent == 0
    assert trialists.emails.skipped == trialists.counted > 100
    assert held_out.emails.skipped == held_out.counted > 0


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


def test_every_stay_gets_its_result_on_the_day_its_horizon_closes_and_not_before(run: RunResult) -> None:
    horizons = {Segment.IDLE: 8, Segment.DRAFTER: 12, Segment.TRIALIST: 14}
    for approach in Approach:
        start = run.by_start[1000]
        results = start.results[approach]
        stays = [stay for j in start.journeys[approach] for stay in j.stays if stay.counted]

        assert len(results) == len(stays)
        assert [r.known_on for r in results] == sorted(r.known_on for r in results)
        for r in results:
            assert r.known_on == r.entered + horizons[r.segment]
            assert r.reached == (r.goal_day is not None and r.goal_day <= r.known_on)


def test_only_stays_entered_by_the_end_of_week_13_are_counted(run: RunResult) -> None:
    for approach in Approach:
        stays = [stay for j in run.by_start[1000].journeys[approach] for stay in j.stays]
        assert all(stay.counted == (stay.entered <= 13 * 7) for stay in stays)
        assert any(not stay.counted for stay in stays)  # merchants keep moving after week 13


# Every email is read and clicked, and every click leads to the goal action within minutes.
CERTAIN_EVERYWHERE = {"idle": CERTAIN_EMAIL, "drafter": CERTAIN_EMAIL, "trialist": CERTAIN_EMAIL}


def test_a_merchant_signing_up_at_the_end_of_week_13_can_still_pay_within_30_days() -> None:
    # Worked by hand: emails on days 2, 4 and 6 after signup (the 48-hour gap), each acted on at once,
    # so every Idle merchant pays about 6 days after signing up. The last signups arrive on day 91,
    # so they draft, publish and pay after week 13; their 30-day window must not be cut off.
    start = run_simulation(with_segments(**CERTAIN_EVERYWHERE), seed=1).by_start[1000]
    idle = start.outcomes[Segment.IDLE]

    assert idle[Approach.HAND_WRITTEN].paid_in_window == idle[Approach.HAND_WRITTEN].counted
    assert idle[Approach.HAND_WRITTEN].counted + start.baselines[Segment.IDLE].counted == IDLE_FROM_1000
    assert idle[Approach.NO_EMAIL].paid_in_window == 0


def test_a_payment_more_than_30_days_after_entering_a_segment_does_not_count_for_it() -> None:
    # Worked by hand: drafting and paying each come about 2 days after their email, but Drafters only
    # publish on their own, after 40 days on average. An Idle merchant pays about 4 days + that wait
    # after entering Idle, so it pays within 30 days only if publishing takes under 26 days:
    # 1 - e^(-26/40) = 47.8% of about 2,350 emailed merchants (chance moves this by about a point).
    slow_publish = {"organic_share": 1.0, "organic_mean_days": 40, "act_rate": 0.0}
    settings = with_segments(idle=CERTAIN_EMAIL, drafter=slow_publish, trialist=CERTAIN_EMAIL)
    idle = run_simulation(settings, seed=1).by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN]

    assert 0.44 < idle.paid_in_window / idle.counted < 0.52


def test_an_email_is_scored_on_the_day_its_miss_window_closes_and_never_before(run: RunResult) -> None:
    # Idle and Drafter emails wait 3 and 7 days from the email; every Trialist email waits until 14 days after publishing.
    start = run.by_start[1000]
    results = start.email_results[Approach.HAND_WRITTEN]
    sent = [s for j in start.journeys[Approach.HAND_WRITTEN] for s in j.stays if s.counted and s.email is EmailFate.SENT]

    assert len(results) == len(sent)
    assert [r.known_on for r in results] == sorted(r.known_on for r in results)
    for r in results:
        closes = {Segment.IDLE: r.sent_on + 3, Segment.DRAFTER: r.sent_on + 7, Segment.TRIALIST: r.entered + 14}[r.segment]
        assert r.known_on == closes
        assert r.hit == (r.goal_day is not None and r.sent_on <= r.goal_day <= r.known_on)
    assert start.email_results[Approach.NO_EMAIL] == []


def test_a_draft_started_after_the_miss_window_is_a_miss_even_inside_the_horizon() -> None:
    # Worked by hand: drafting comes 3 days after the click on average. The email is a hit only if the
    # draft starts within the 3-day miss window: 1 - e^(-1) = 63.2% of emails. It still counts as
    # reached for true lift if the draft starts within the 6 days left of the 8-day horizon: 1 - e^(-2) = 86.5%.
    settings = with_idle(**{**CERTAIN_EMAIL, "response_mean_days": 3})
    idle = run_simulation(settings, seed=1).by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN]

    assert idle.emails.hits + idle.emails.misses == idle.emails.sent == idle.counted
    assert 0.60 < idle.emails.hits / idle.emails.sent < 0.66
    assert 0.84 < idle.reached_share < 0.89


def test_every_trialist_who_pays_brings_40_dollars_of_first_month_revenue(run: RunResult) -> None:
    # The AI loop's discount offer is the exception (tests/test_offers.py).
    trialists = run.by_start[1000].outcomes[Segment.TRIALIST]

    for approach in (Approach.NO_EMAIL, Approach.HAND_WRITTEN):
        assert trialists[approach].reached > 0
        assert trialists[approach].first_month_revenue == 40 * trialists[approach].reached
    assert run.by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN].first_month_revenue == 0


def test_the_report_shows_hits_misses_paid_conversion_and_trialist_revenue() -> None:
    # Every email works at once, so every emailed merchant hits, pays within days, and brings $40.
    run = run_simulation(with_segments(**CERTAIN_EVERYWHERE), seed=1)
    trialists = run.by_start[1000].outcomes[Segment.TRIALIST][Approach.HAND_WRITTEN]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]
    idle_part, rest = from_1000.split("### Drafter: publish", 1)
    trialist_part = rest.split("### Trialist: pay", 1)[1]

    emailed = run.by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN].counted
    assert f"| Hand-written email (your first draft) | {emailed:,} | 100.0% | +100.0 | 100.0% |" in idle_part
    assert f"| No email | {emailed:,} | 0.0% | reference | 0.0% |" in idle_part
    assert f"| Hand-written email (your first draft) | {emailed:,} | 0 | {emailed:,} | 0 |" in idle_part
    assert "within 3 days of the email" in idle_part
    assert "An email is a hit if the merchant paid within 14 days of publishing" in trialist_part
    assert f"| ${trialists.first_month_revenue:,.0f} |" in trialist_part and trialists.first_month_revenue > 0


def test_a_trialist_who_would_pay_on_day_8_does_not_pay_in_a_7_day_trial() -> None:
    # The same merchants with the same luck, once with a 9-day trial and once with the real 7 days.
    # With no email, every Trialist would pay on its own about 8 days after publishing.
    slow = with_segments(trialist={"organic_share": 1.0, "organic_mean_days": 8})

    def paid_after_publishing(trial_days: float) -> dict[str, float | None]:
        journeys = run_simulation(dataclasses.replace(slow, trial_days=trial_days), seed=1).by_start[1000].journeys[Approach.NO_EMAIL]
        trialists = [j for j in journeys if j.merchant.start_segment is Segment.TRIALIST]
        return {j.merchant.key: None if j.stays[0].left is None else j.stays[0].left - j.stays[0].entered for j in trialists}

    longer, real = paid_after_publishing(9), paid_after_publishing(7)
    on_day_8_or_9 = [key for key, day in longer.items() if day is not None and 7 < day <= 9]

    assert len(on_day_8_or_9) > 5
    assert all(real[key] is None for key in on_day_8_or_9)


def holdout(journeys: list[Journey]) -> list[Journey]:
    return [j for j in journeys if j.merchant.holdout]


def test_about_8_percent_of_merchants_are_held_out_the_same_in_every_approach(run: RunResult) -> None:
    # 2,915 simulated merchants at 8%: chance moves the share by about half a point.
    start = run.by_start[1000]
    share = sum(m.holdout for m in start.merchants) / len(start.merchants)

    assert 0.065 < share < 0.095
    for approach in Approach:
        assert [j.merchant.holdout for j in start.journeys[approach]] == [m.holdout for m in start.merchants]


def test_no_holdout_merchant_ever_receives_an_email_but_each_gets_a_ghost_send(run: RunResult) -> None:
    for start in (run_simulation(with_segments(**CERTAIN_EVERYWHERE), seed=1).by_start[1000], run.by_start[1000]):
        held = holdout(start.journeys[Approach.HAND_WRITTEN])
        held_keys = {j.merchant.key for j in held}

        assert held
        assert all(stay.email not in (EmailFate.SENT, EmailFate.SKIPPED) for j in held for stay in j.stays)
        assert not any(r.merchant_key in held_keys for r in start.email_results[Approach.HAND_WRITTEN])
        assert all(stay.email is not EmailFate.NOT_PLANNED for j in held for stay in j.stays if stay.counted)
        for segment in Segment:
            assert (start.baselines[segment].emails.hits, start.baselines[segment].emails.misses) == (0, 0)


def test_ghost_sends_are_skipped_like_real_ones_and_counted_apart() -> None:
    everyone_drafts_fast = with_idle(organic_share=1.0, organic_mean_days=0.01)
    start = run_simulation(everyone_drafts_fast, seed=1).by_start[1000]
    email = start.outcomes[Segment.IDLE][Approach.HAND_WRITTEN]
    ghost = start.baselines[Segment.IDLE]

    assert (email.emails.sent, ghost.emails.sent) == (0, 0)
    assert email.emails.skipped == email.counted
    assert ghost.emails.skipped == ghost.counted > 0


def test_ghost_sends_keep_48_hours_apart_like_real_ones() -> None:
    # As in the real-email test: the Drafter email would be due 6 hours after the Idle one.
    settings = with_segments(idle={**CERTAIN_EMAIL, "organic_share": 1.0, "organic_mean_days": 2.1}, drafter={"hand_written_after_days": 0.25})
    held = holdout(run_simulation(settings, seed=1).by_start[1000].journeys[Approach.HAND_WRITTEN])

    held_back = 0
    for journey in held:
        ghosts = [s.email_sent_at for s in journey.stays if s.email is EmailFate.GHOST_SENT and s.email_sent_at is not None]
        assert all(later - earlier >= 2 - 1e-9 for earlier, later in zip(ghosts, ghosts[1:]))
        held_back += any(s.segment is Segment.DRAFTER and s.email is EmailFate.GHOST_SENT and s.email_sent_at is not None and s.email_sent_at > s.entered + 0.25 for s in journey.stays)
    assert held_back > 0


def test_true_lift_compares_only_emailed_merchants_with_the_same_merchants_without_email() -> None:
    # Every emailed Idle merchant drafts; nobody drafts alone. Counting the holdout would show 92%, not 100%.
    start = run_simulation(with_idle(**CERTAIN_EMAIL), seed=1).by_start[1000]
    idle = start.outcomes[Segment.IDLE]
    emailed = sum(m.start_segment is Segment.IDLE and not m.holdout for m in start.merchants)

    assert idle[Approach.HAND_WRITTEN].counted == idle[Approach.NO_EMAIL].counted == emailed
    assert idle[Approach.HAND_WRITTEN].reached_share == 1.0
    assert idle[Approach.HAND_WRITTEN].true_lift == 1.0


def test_each_segments_baseline_is_the_holdouts_goal_rate_and_matches_no_email_for_them(run: RunResult) -> None:
    start = run.by_start[1000]
    for segment in Segment:
        baseline = start.baselines[segment]
        held_keys = {j.merchant.key for j in holdout(start.journeys[Approach.HAND_WRITTEN])}
        no_email = [r for r in start.results[Approach.NO_EMAIL] if r.segment is segment and r.merchant_key in held_keys]

        assert baseline.counted == len(no_email) > 0
        assert baseline.reached == sum(r.reached for r in no_email)


def test_the_report_shows_each_segments_baseline_and_ghost_sends_apart_from_real_ones(run: RunResult) -> None:
    start = run.by_start[1000]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]
    headings = {Segment.IDLE: "### Idle: start a draft", Segment.DRAFTER: "### Drafter: publish", Segment.TRIALIST: "### Trialist: pay"}

    for segment, heading in headings.items():
        baseline = start.baselines[segment]
        email = start.outcomes[segment][Approach.HAND_WRITTEN].emails + start.pushed[segment][Approach.HAND_WRITTEN].emails
        section = from_1000.split(heading, 1)[1].split("### ", 1)[0]
        assert f"| Holdout (never emailed) | {baseline.counted:,} | {baseline.reached_share:.1%} | baseline |" in section
        assert f"| Holdout (ghost sends: nothing sent) | {baseline.emails.sent:,} | {baseline.emails.skipped:,} | – | – |" in section
        assert f"| Hand-written email (your first draft) | {email.sent:,} | {email.skipped:,} |" in section


def test_the_report_warns_that_its_numbers_rest_on_placeholders_and_how_much_chance_moves_the_holdout(run: RunResult) -> None:
    start = run.by_start[1000]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]
    idle = start.baselines[Segment.IDLE]
    # Worked by hand for the Idle holdout: 1.96 x sqrt(p(1 - p) / n) is the 95% margin of a share.
    margin = 1.96 * (idle.reached_share * (1 - idle.reached_share) / idle.counted) ** 0.5 * 100

    assert "rests on placeholder settings" in from_1000
    assert f"chance alone moves its rate by about ±{margin:.1f} points" in from_1000.split("### Idle: start a draft", 1)[1].split("### ", 1)[0]


def test_the_run_lasts_until_the_last_signups_30_day_paid_window_has_closed() -> None:
    # Worked by hand: emails 2, 8 and 6 days after each trigger, each acted on at once, so every emailed
    # Idle merchant pays about 16 days after signing up. The last signups (day 91) pay around day 107,
    # after every horizon and miss window has closed; only their 30-day paid window keeps the run going.
    late = {"idle": CERTAIN_EMAIL, "drafter": {**CERTAIN_EMAIL, "hand_written_after_days": 8}, "trialist": {**CERTAIN_EMAIL, "hand_written_after_days": 6}}
    idle = run_simulation(with_segments(**late), seed=1).by_start[1000].outcomes[Segment.IDLE][Approach.HAND_WRITTEN]

    assert idle.paid_in_window == idle.counted


def test_each_later_segment_is_judged_on_the_merchants_who_would_be_there_with_no_email(run: RunResult) -> None:
    start = run.by_start[1000]
    for segment in (Segment.DRAFTER, Segment.TRIALIST):
        counted = {a: start.outcomes[segment][a].counted for a in Approach}
        assert len(set(counted.values())) == 1, counted
        # Merchants an earlier email pushed into the segment are reported on their own.
        assert start.pushed[segment][Approach.NO_EMAIL].counted == 0
        assert start.pushed[segment][Approach.HAND_WRITTEN].counted > 0
    assert all(start.pushed[Segment.IDLE][a].counted == 0 for a in Approach)


def test_when_no_email_can_cost_a_merchant_its_goal_no_segment_shows_a_negative_true_lift() -> None:
    # An email can only add or bring forward a goal action, never take one away, so judged on the
    # same merchants every true lift is zero or more. The old comparison showed -0.2 points for
    # Trialists at 1,500 merchants with seed 1.
    settings = load_settings(SETTINGS)
    for seed in (1, 2, 3):
        for start in run_simulation(settings, seed=seed).by_start.values():
            for segment in Segment:
                for approach in (Approach.HAND_WRITTEN, Approach.AI_LOOP):
                    assert start.outcomes[segment][approach].true_lift >= 0, (seed, segment, approach)


def test_the_report_shows_merchants_pushed_into_a_segment_by_an_earlier_email(run: RunResult) -> None:
    start = run.by_start[1000]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]
    drafter_part = from_1000.split("### Drafter: publish", 1)[1].split("### ", 1)[0]
    pushed = start.pushed[Segment.DRAFTER][Approach.HAND_WRITTEN]

    assert f"| Hand-written email (your first draft): pushed here by an earlier email | {pushed.counted:,} | {pushed.reached_share:.1%} |" in drafter_part
