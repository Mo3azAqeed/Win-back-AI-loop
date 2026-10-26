"""Every rule that is only about Trialists: the trial, the offers an AI loop email can carry, what a
Trialist pays, and when its email is judged."""

import math
from enum import Enum
from typing import TYPE_CHECKING

from winback.segments import Segment

if TYPE_CHECKING:  # the settings hold each offer's terms, so they import this module
    from winback.settings import OfferSettings, Settings


class Offer(Enum):
    NONE = "no offer"
    EXTENSION = "more trial days"
    DISCOUNT = "first-month discount"


# Where each segment's miss window starts: every Trialist is judged from publishing, whatever its offer.
MISS_WINDOW_FROM = {Segment.IDLE: "the email", Segment.DRAFTER: "the email", Segment.TRIALIST: "publishing"}


def deadline(settings: "Settings", segment: Segment, entered: float) -> float:
    """The last day a merchant in this segment can take the goal action: a Trialist must pay before its trial
    ends; the other segments have no deadline."""
    return entered + settings.trial_days if segment is Segment.TRIALIST else math.inf


def extended(offers: "OfferSettings", deadline: float) -> float:
    """The deadline of a Trialist who has been sent more trial days."""
    return deadline + offers.extra_trial_days


def act_rate(offers: "OfferSettings", act_rate: float, received: Offer | None) -> float:
    """How likely a merchant who clicks is to act, with the offer it received (if any)."""
    return act_rate * (1 + offers.pay_lift[received]) if received is not None else act_rate


def discounted(received: Offer | None, clicked: bool) -> bool:
    """The discount only works through the email's link: a merchant who clicked it before paying pays the
    discounted price, even one who would have paid in full anyway."""
    return received is Offer.DISCOUNT and clicked


def first_month_revenue(settings: "Settings", discounted: bool) -> float:
    return settings.monthly_price * (settings.offers.discount_price_share if discounted else 1.0)


def miss_window_opens(segment: Segment, entered: float, sent: float) -> float:
    return entered if segment is Segment.TRIALIST else sent


def offer_labels(offers: "OfferSettings") -> dict[Offer, str]:
    return {
        Offer.NONE: "No offer",
        Offer.EXTENSION: f"{offers.extra_trial_days:g} more trial days",
        Offer.DISCOUNT: f"First month {1 - offers.discount_price_share:.0%} off",
    }
