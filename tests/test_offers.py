import dataclasses

import pytest

import re
import tomllib

from winback import Approach, Offer, RunResult, Segment, Settings, StartResult, load_settings, run_simulation
from winback.lifecycle import EmailFate, Stay
from winback.trialist import offer_labels

from conftest import SETTINGS, only, with_segment

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


def test_a_trialist_who_clicks_the_discount_pays_20_dollars_and_any_other_payment_is_40(run: RunResult) -> None:
    # The discount only works through the email's link (founder's decision), so a Trialist who got the
    # discount email but never clicked it pays the full price.
    start = run.by_start[1000]
    stays = {(key, s.entered): s for key, s in trialist_stays(start, Approach.AI_LOOP)}
    paid = [r for r in start.results[Approach.AI_LOOP] if r.segment is Segment.TRIALIST and r.reached]
    got_discount = [r for r in paid if received(stays[(r.merchant_key, r.entered)], Offer.DISCOUNT)]

    discounted = [r for r in got_discount if stays[(r.merchant_key, r.entered)].clicked]
    assert discounted and all(r.first_month_revenue == 20 for r in discounted)
    assert any(r not in discounted for r in got_discount)
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
    # The discount no longer makes anyone more likely to pay, so it brings the same payers as no offer,
    # but those who click it pay half: by revenue it is worse than no offer. Half of Trialist readers
    # click here, so its cost shows within 13 weeks. Over the second half of the run the AI loop sends it
    # clearly less often than no offer. A judge counting payments instead of revenue couldn't tell them
    # apart. One seed can be lucky, so six are averaged.
    settings = with_pay_lift(only(load_settings(SETTINGS), 1000), Offer.DISCOUNT, 0.0)
    trialist = dataclasses.replace(settings.segments[Segment.TRIALIST], click_rate=0.5)
    settings = dataclasses.replace(settings, segments={**settings.segments, Segment.TRIALIST: trialist})
    gaps = []
    for seed in range(1, 7):
        start = run_simulation(settings, seed=seed).by_start[1000]
        held = {j.merchant.key for j in start.journeys[Approach.AI_LOOP] if j.merchant.holdout}
        emailed = sorted((s for key, s in trialist_stays(start, Approach.AI_LOOP) if s.counted and key not in held), key=lambda s: s.entered)
        late = emailed[len(emailed) // 2 :]
        gaps.append((sum(s.offer is Offer.NONE for s in late) - sum(s.offer is Offer.DISCOUNT for s in late)) / len(late))

    assert sum(gaps) / len(gaps) > 0.07


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
        r.merchant_key for r in start.results[Approach.AI_LOOP]
        if r.segment is Segment.TRIALIST and r.reached and received(stays[(r.merchant_key, r.entered)], Offer.DISCOUNT) and stays[(r.merchant_key, r.entered)].clicked
    }
    paid_alone = {j.merchant.key for j in start.journeys[Approach.NO_EMAIL] if j.paid_at is not None}

    assert start.offers.discounted_payers == len(discounted)
    assert start.offers.would_have_paid_anyway == len(discounted & paid_alone)


def test_each_offer_is_named_from_its_settings() -> None:
    offers = dataclasses.replace(load_settings(SETTINGS).offers, extra_trial_days=10, discount_price_share=0.25)

    assert offer_labels(offers) == {Offer.NONE: "No offer", Offer.EXTENSION: "10 more trial days", Offer.DISCOUNT: "First month 75% off"}


def test_each_offer_line_is_on_the_fact_sheet_and_matches_the_offer_settings() -> None:
    settings = load_settings(SETTINGS)
    fact_sheet = tomllib.loads((SETTINGS.parent / "fact_sheet.toml").read_text())
    lines = settings.offers.lines

    assert set(fact_sheet["offers"].values()) == {lines[Offer.EXTENSION], lines[Offer.DISCOUNT]}
    assert re.findall(r"\d+", lines[Offer.EXTENSION]) == [f"{settings.offers.extra_trial_days:g}"]
    discounted, full = re.findall(r"\$(\d+)", lines[Offer.DISCOUNT])
    assert (float(discounted), float(full)) == (settings.monthly_price * settings.offers.discount_price_share, settings.monthly_price)


def test_each_offer_changes_how_likely_a_trialist_who_clicks_is_to_pay_by_its_own_setting() -> None:
    # Hidden truth: a Trialist who clicks pays 25% of the time with no offer. Here more trial days change
    # nothing and the discount triples it (pay lift 2.0). Nobody pays on their own, so every payer was the email's.
    settings = with_segment(only(load_settings(SETTINGS), 1500), Segment.TRIALIST, organic_share=0.0, act_rate=0.25)
    settings = with_pay_lift(with_pay_lift(settings, Offer.EXTENSION, 0.0), Offer.DISCOUNT, 2.0)
    # The AI loop soon favours the discount, so three seeds are pooled to see enough clicks on every offer.
    stays = [s for seed in (1, 2, 3) for _, s in trialist_stays(run_simulation(settings, seed=seed).by_start[1500], Approach.AI_LOOP) if s.clicked]

    def pay_rate(offer: Offer) -> float:
        clicked = [s for s in stays if s.offer is offer]
        assert len(clicked) > 15
        return sum(s.left is not None for s in clicked) / len(clicked)

    assert pay_rate(Offer.NONE) < 0.4 and pay_rate(Offer.EXTENSION) < 0.4
    assert pay_rate(Offer.DISCOUNT) > 0.6


def test_a_slow_payer_given_more_trial_days_can_pay_until_day_14_and_no_later() -> None:
    # Every Trialist would pay on its own about 12 days after publishing, often after day 7 and sometimes after day 14.
    settings = with_segment(only(load_settings(SETTINGS), 1000), Segment.TRIALIST, organic_share=1.0, organic_mean_days=12)
    stays = [s for _, s in trialist_stays(run_simulation(settings, seed=1).by_start[1000], Approach.AI_LOOP)]
    extended = [s for s in stays if received(s, Offer.EXTENSION)]
    paid_after = [s.left - s.entered for s in extended if s.left is not None]

    assert sum(7 < day <= 14 for day in paid_after) > 10
    assert all(day <= 14 for day in paid_after)
    assert any(s.left is None for s in extended)  # some would only have paid after day 14


def test_the_holdout_never_gets_an_offers_effect(run: RunResult) -> None:
    start = run.by_start[1000]
    held = {j.merchant.key for j in start.journeys[Approach.AI_LOOP] if j.merchant.holdout}
    paid = [(r, s) for r in start.results[Approach.AI_LOOP] if r.merchant_key in held and r.segment is Segment.TRIALIST and r.reached
            for key, s in trialist_stays(start, Approach.AI_LOOP) if key == r.merchant_key]

    assert paid
    assert all(r.first_month_revenue == 40 and s.left is not None and s.left - s.entered <= 7 for r, s in paid)


def test_the_report_shows_what_each_offer_has_earned_per_trialist(run: RunResult) -> None:
    start = run.by_start[1000]
    from_1000 = run.report.split("## Starting from 1,000 merchants", 1)[1].split("## Starting from 1,500", 1)[0]
    discount = next(o for o in start.loop.offers if o.offer is Offer.DISCOUNT)

    assert f"| First month 50% off | {discount.assigned:,} | ${40 * discount.revenue_share / discount.assigned:,.2f} |" in from_1000


def test_each_offers_settings_are_read_for_that_offer() -> None:
    settings = load_settings(SETTINGS)
    written = tomllib.loads(SETTINGS.read_text())["offers"]

    assert settings.offers.pay_lift == {
        Offer.NONE: 0.0,
        Offer.EXTENSION: written["extension_pay_lift"]["value"],
        Offer.DISCOUNT: written["discount_pay_lift"]["value"],
    }
    assert settings.offers.pay_lift[Offer.EXTENSION] != settings.offers.pay_lift[Offer.DISCOUNT]
    assert (settings.offers.extra_trial_days, settings.offers.discount_price_share) == (written["extra_trial_days"]["value"], written["discount_price_share"]["value"])
