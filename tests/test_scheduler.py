from datetime import datetime, timezone

import pytest

from app.scheduler import next_run, parse_times

TIMES = ["10:00", "22:00"]


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_next_run_later_today():
    # 02:00 UTC = 08:00 in Dhaka -> next run is 10:00 Dhaka the same day
    run = next_run(utc(2026, 11, 1, 2, 0), TIMES, "Asia/Dhaka")
    assert (run.hour, run.minute, run.day) == (10, 0, 1)
    assert run.astimezone(timezone.utc) == utc(2026, 11, 1, 4, 0)


def test_next_run_evening():
    run = next_run(utc(2026, 11, 1, 5, 0), TIMES, "Asia/Dhaka")  # 11:00 Dhaka
    assert (run.hour, run.day) == (22, 1)


def test_next_run_rolls_over_to_tomorrow():
    run = next_run(utc(2026, 11, 1, 17, 0), TIMES, "Asia/Dhaka")  # 23:00 Dhaka
    assert (run.hour, run.day) == (10, 2)


def test_exactly_on_time_waits_for_the_next_one():
    run = next_run(utc(2026, 11, 1, 4, 0), TIMES, "Asia/Dhaka")  # exactly 10:00 Dhaka
    assert run.hour == 22


def test_bad_time_is_rejected():
    with pytest.raises(ValueError):
        parse_times(["25:00"])
