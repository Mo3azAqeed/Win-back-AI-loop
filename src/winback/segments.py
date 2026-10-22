"""The segments a stalled merchant can be in. Paying is an outcome, not a segment."""

from enum import Enum


class Segment(Enum):
    IDLE = "idle"
    DRAFTER = "drafter"
    TRIALIST = "trialist"


# The segment a merchant moves to after taking the goal action; None means they paid.
NEXT_SEGMENT: dict[Segment, Segment | None] = {Segment.IDLE: Segment.DRAFTER, Segment.DRAFTER: Segment.TRIALIST, Segment.TRIALIST: None}
