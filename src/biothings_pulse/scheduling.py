"""Schedule helpers: honor a plugin's own cron schedule, else a default interval.

A plugin may declare a cron schedule (manifest ``dumper.schedule`` or an advanced
dumper's ``SCHEDULE``). When present we follow it; otherwise a source is checked
every ``default_interval`` seconds. ``croniter`` (a BioThings dependency) parses
the cron expressions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from croniter import croniter


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_valid_cron(schedule: Optional[str]) -> bool:
    return bool(schedule) and croniter.is_valid(schedule)


def next_check_at(
    schedule: Optional[str],
    last_checked: Optional[datetime],
    default_interval: float,
    now: Optional[datetime] = None,
) -> datetime:
    """When the next check is due.

    Cron schedule -> the next cron time after the last check (or now if never
    checked). No/invalid schedule -> last check + ``default_interval`` (or now).
    """
    now = now or _now()
    base = last_checked or now
    if is_valid_cron(schedule):
        return croniter(schedule, base).get_next(datetime)
    return base + timedelta(seconds=default_interval)


def is_due(
    schedule: Optional[str],
    last_checked: Optional[datetime],
    default_interval: float,
    now: Optional[datetime] = None,
) -> bool:
    """True if a source should be checked now (never-checked is always due)."""
    now = now or _now()
    if last_checked is None:
        return True
    return next_check_at(schedule, last_checked, default_interval, now) <= now
