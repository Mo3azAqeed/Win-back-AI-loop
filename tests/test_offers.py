import dataclasses
from pathlib import Path

import pytest

from winback import Approach, RunResult, Segment, Settings, StartResult, load_settings, run_simulation
from winback.lifecycle import EmailFate, Stay
from winback.offers import Offer

SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"


@pytest.fixture(scope="module")
def run() -> RunResult:
    return run_simulation(load_settings(SETTINGS), seed=1)


def with_pay_lift(settings: Settings, offer: Offer, lift: float) -> Settings:
    return dataclasses.replace(settings, offers=dataclasses.replace(settings.offers, pay_lift={**settings.offers.pay_lift, offer: lift}))


def trialist_stays(start: StartResult, approach: Approach) -> list[tuple[str, Stay]]:
    return [(j.merchant.key, s) for j in start.journeys[approach] for s in j.stays if s.segment is Segment.TRIALIST]


def received(stay: Stay, offer: Offer) -> bool:
    """The merchant got an email with this offer before it paid (or at all, if it never paid)."""
    return stay.offer is offer and stay.email is EmailFate.SENT and stay.email_sent_at is not None and (stay.left is None or stay.email_sent_at <= stay.left)


def test_only_trialists_get_offers_and_only_from_the_ai_loop(run: RunResult) -> None:
    start = run.by_start[1000]

    for approach in Approach:
        for journey in start.journeys[approach]:
            for stay in journey.stays:
                if approach is Approach.AI_LOOP and stay.segment is Segment.TRIALIST:
                    assert stay.offer is not None
                else:
                    assert stay.offer is None
    sent = [s for _, s in trialist_stays(start, Approach.AI_LOOP) if s.email is EmailFate.SENT]
    assert {s.offer for s in sent} == set(Offer)


def test_a_discounted_payment_brings_20_dollars_and_any_other_payment_40(run: RunResult) -> None:
    start = run.by_start[1000]
    stays = {(key, s.entered): s for key, s in trialist_stays(start, Approach.AI_LOOP)}
    paid = [r for r in start.results[Approach.AI_LOOP] if r.segment is Segment.TRIALIST and r.reached]

    discounted = [r for r in paid if received(stays[(r.merchant_key, r.entered)], Offer.DISCOUNT)]
    assert discounted and all(r.first_month_revenue == 20 for r in discounted)
    assert all(r.first_month_revenue == 40 for r in paid if r not in discounted)
    for approach in (Approach.NO_EMAIL, Approach.HAND_WRITTEN):
        assert {r.first_month_revenue for r in start.results[approach] if r.segment is Segment.TRIALIST and r.reached} == {40}


def test_more_trial_days_let_a_trialist_pay_until_day_14_and_others_only_until_day_7(run: RunResult) -> None:
    stays = [s for _, s in trialist_stays(run.by_start[1000], Approach.AI_LOOP) if s.left is not None]
    extended = [s for s in stays if received(s, Offer.EXTENSION)]

    assert all(s.left is not None and s.left - s.entered <= 14 for s in extended)
    assert any(s.left is not None and s.left - s.entered > 7 for s in extended)
    assert all(s.left is not None and s.left - s.entered <= 7 for s in stays if s not in extended)


def test_the_offer_learns_from_revenue_so_a_discounted_payment_counts_as_half(run: RunResult) -> None:
    start = run.by_start[1000]
    held = {j.merchant.key for j in start.journeys[Approach.AI_LOOP] if j.merchant.holdout}
    stays = {(key, s.entered): s for key, s in trialist_stays(start, Approach.AI_LOOP)}
    judged = [r for r in start.results[Approach.AI_LOOP] if r.segment is Segment.TRIALIST and r.merchant_key not in held]
    records = {o.offer: o for o in start.loop.offers}

    for offer in Offer:
        assigned = [r for r in judged if stays[(r.merchant_key, r.entered)].offer is offer]
        assert records[offer].assigned == len(assigned)
        assert records[offer].revenue_share == pytest.approx(sum(r.first_month_revenue for r in assigned) / 40)
    assert 0 < records[Offer.DISCOUNT].revenue_share < sum(r.reached for r in judged if stays[(r.merchant_key, r.entered)].offer is Offer.DISCOUNT)


def test_when_the_discount_does_nothing_for_paying_the_ai_loop_stops_choosing_it() -> None:
    # The discount halves revenue and no longer makes anyone more likely to pay, so it is truly worst.
    # Early on the three offers share the Trialists; by the last third of the run the discount gets far
    # fewer of them, in every seed, and it never ends up ahead.
    settings = with_pay_lift(dataclasses.replace(load_settings(SETTINGS), start_sizes=(1000,)), Offer.DISCOUNT, 0.0)
    early, late, leading = [], [], 0
    for seed in range(1, 7):
        start = run_simulation(settings, seed=seed).by_start[1000]
        held = {j.merchant.key for j in start.journeys[Approach.AI_LOOP] if j.merchant.holdout}
        emailed = sorted((s for key, s in trialist_stays(start, Approach.AI_LOOP) if s.counted and key not in held), key=lambda s: s.entered)
        third = len(emailed) // 3
        early.append(sum(s.offer is Offer.DISCOUNT for s in emailed[:third]) / third)
        late.append(sum(s.offer is Offer.DISCOUNT for s in emailed[-third:]) / third)
        leading += next(o for o in start.loop.offers if o.offer is Offer.DISCOUNT).leading

    assert all(l < e for e, l in zip(early, late))
    assert sum(late) / len(late) < 0.2
    assert leading == 0


def test_the_report_shows_offers_sent_revenue_and_discounted_payers_who_would_have_paid_anyway(run: RunResult) -> None:
    settings = load_settings(SETTINGS)
    start = run.by_start[1000]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]
    trialist_part = from_1000.split("### Trialist: pay", 1)[1].split("### What the AI loop is sending", 1)[0]
    summary = start.offers

    sent = [s for _, s in trialist_stays(start, Approach.AI_LOOP) if s.email is EmailFate.SENT and s.counted]
    for offer in Offer:
        assert summary.sent[offer] == sum(s.offer is offer for s in sent)
        line = settings.offers.lines[offer] or "–"
        assert f"| {line} | {summary.sent[offer]:,} |" in trialist_part
    assert 0 < summary.would_have_paid_anyway <= summary.discounted_payers
    assert (
        f"{summary.discounted_payers:,} Trialists paid with the discount; {summary.would_have_paid_anyway:,} of them "
        "would have paid the full $40 with no email." in trialist_part
    )
    ai = start.outcomes[Segment.TRIALIST][Approach.AI_LOOP]
    assert f"| AI loop | {ai.counted:,} |" in trialist_part and f" ${ai.first_month_revenue:,.0f} |" in trialist_part


def test_discounted_payers_who_would_have_paid_anyway_are_those_who_paid_with_no_email(run: RunResult) -> None:
    start = run.by_start[1000]
    stays = {(key, s.entered): s for key, s in trialist_stays(start, Approach.AI_LOOP)}
    discounted = {
        r.merchant_key for r in start.results[Approach.AI_LOOP] if r.segment is Segment.TRIALIST and r.reached and received(stays[(r.merchant_key, r.entered)], Offer.DISCOUNT)
    }
    paid_alone = {r.merchant_key for r in start.results[Approach.NO_EMAIL] if r.segment is Segment.TRIALIST and r.reached}

    assert start.offers.discounted_payers == len(discounted)
    assert start.offers.would_have_paid_anyway == len(discounted & paid_alone)
