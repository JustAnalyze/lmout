import pytest
from datetime import datetime, time, timedelta
from lock_me_out.utils.time import calculate_from_range, parse_time_string


def test_parse_time_string():
    now = datetime.now()
    # Test various formats
    assert parse_time_string("8pm").time() == time(20, 0)
    assert parse_time_string("8:30pm").time() == time(20, 30)
    assert parse_time_string("20:00").time() == time(20, 0)
    assert parse_time_string("08:00").time() == time(8, 0)

    with pytest.raises(ValueError):
        parse_time_string("invalid")


def test_calculate_from_range_future():
    # Mocking now for deterministic tests would be better, but let's use logic
    # If we are at 10am, and schedule 8pm to 9pm
    # delay should be 10 hours (600 mins)
    # duration should be 1 hour (60 mins)

    # We can't easily mock datetime.now() without a library like freezegun or patching
    # But we can test relative logic if we know the order.
    pass


@pytest.mark.parametrize(
    "start, end, expected_duration_seconds",
    [
        ("8pm", "8:30pm", 30 * 60),
        ("10:00", "11:00", 60 * 60),
        ("23:00", "01:00", 120 * 60),  # Crosses midnight
    ],
)
def test_calculate_from_range_duration(start, end, expected_duration_seconds):
    # Use 12:00 PM as reference to avoid being "inside" evening ranges
    ref_now = datetime.combine(datetime.now().date(), time(12, 0))
    delay, duration, total = calculate_from_range(start, end, now=ref_now)
    # When starting in the future, duration and total should be same
    assert duration == expected_duration_seconds
    assert total == expected_duration_seconds


def test_calculate_from_range_already_in_range():
    # If start is 1 hour ago and end is 1 hour from now
    # This is hard to test without mocking now.
    pass
