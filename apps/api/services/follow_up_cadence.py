"""
Cadence Configuration Foundation for Follow-up Sequences.

Default Approved Cadence (relative to initial outreach send):
- Step 1: 2 days (48 hours)
- Step 2: 5 days (120 hours)
- Step 3: 10 days (240 hours)

Enables configurable cadences while keeping schedule calculations deterministic and isolated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Sequence

from schemas.follow_up import CadenceStepConfig


DEFAULT_CADENCE_DELAYS_HOURS: List[int] = [48, 120, 240]


@dataclass(frozen=True)
class CadencePlanItem:
    step_number: int
    delay_hours: int
    scheduled_at: datetime


def get_default_cadence() -> List[CadenceStepConfig]:
    """Return default standard 3-step agency outreach follow-up cadence."""
    return [
        CadenceStepConfig(step_number=1, delay_hours=48),
        CadenceStepConfig(step_number=2, delay_hours=120),
        CadenceStepConfig(step_number=3, delay_hours=240),
    ]


def calculate_cadence_schedule(
    base_time: datetime,
    cadence_steps: Sequence[CadenceStepConfig] | None = None,
) -> List[CadencePlanItem]:
    """
    Calculate deterministic scheduled_at timestamps for each step in a cadence,
    relative to base_time (the sent_at timestamp of the original OutreachMessage).
    
    Validates:
    - Step numbers are sequential starting from 1.
    - Delays are strictly increasing.
    """
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=timezone.utc)

    steps = list(cadence_steps) if cadence_steps else get_default_cadence()
    if not steps:
        raise ValueError("Cadence configuration must have at least one step.")

    # Sort steps by step_number
    sorted_steps = sorted(steps, key=lambda s: s.step_number)

    plan: List[CadencePlanItem] = []
    prev_delay = -1

    for idx, s in enumerate(sorted_steps, start=1):
        if s.step_number != idx:
            raise ValueError(f"Cadence step numbers must be sequential 1..N (got step {s.step_number} at index {idx}).")
        if s.delay_hours <= prev_delay:
            raise ValueError(f"Cadence step delay ({s.delay_hours}h) must be strictly greater than previous step ({prev_delay}h).")
        
        scheduled_at = base_time + timedelta(hours=s.delay_hours)
        plan.append(
            CadencePlanItem(
                step_number=s.step_number,
                delay_hours=s.delay_hours,
                scheduled_at=scheduled_at,
            )
        )
        prev_delay = s.delay_hours

    return plan
