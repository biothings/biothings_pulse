from datetime import datetime, timedelta, timezone

from biothings_pulse.scheduling import is_due, is_valid_cron, next_check_at

NOW = datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)  # a Friday
DAY = 86400


def test_never_checked_is_always_due():
    assert is_due("0 2 * * 0", None, DAY, NOW) is True
    assert is_due(None, None, DAY, NOW) is True


def test_default_interval():
    assert is_due(None, NOW - timedelta(hours=2), DAY, NOW) is False
    assert is_due(None, NOW - timedelta(hours=25), DAY, NOW) is True


def test_cron_weekly_not_due_midweek():
    last = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)  # Monday
    assert is_due("0 2 * * 0", last, DAY, NOW) is False  # next is Sunday
    assert next_check_at("0 2 * * 0", last, DAY, NOW) == datetime(
        2026, 7, 26, 2, 0, tzinfo=timezone.utc
    )


def test_cron_due_when_time_passed():
    last = datetime(2026, 7, 19, 1, 0, tzinfo=timezone.utc)
    assert is_due("0 0 * * *", last, DAY, NOW) is True  # daily midnight elapsed


def test_invalid_cron_falls_back_to_interval():
    assert is_valid_cron("nonsense") is False
    assert is_due("nonsense", NOW - timedelta(hours=2), DAY, NOW) is False
    assert is_due("nonsense", NOW - timedelta(hours=25), DAY, NOW) is True
