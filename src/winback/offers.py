"""The offers a Trialist's email from the AI loop can carry."""

from enum import Enum


class Offer(Enum):
    NONE = "no offer"
    EXTENSION = "more trial days"
    DISCOUNT = "first-month discount"
