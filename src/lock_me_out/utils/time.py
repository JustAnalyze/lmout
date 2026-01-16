from datetime import datetime, timedelta


def parse_time_string(time_str: str) -> datetime:
    """Parses time strings like '8pm', '8:30pm', '20:00', '20:30'."""
    formats = ["%I%p", "%I:%M%p", "%H:%M", "%H:%M:%S"]
    time_str = time_str.lower().replace(" ", "")
    now = datetime.now()
    for fmt in formats:
        try:
            parsed_time = datetime.strptime(time_str, fmt).time()
            return datetime.combine(now.date(), parsed_time)
        except ValueError:
            continue
    raise ValueError(f"Could not parse time: {time_str}")


def calculate_from_range(
    start_str: str, end_str: str, now: datetime | None = None
) -> tuple[int, int]:
    """
    Calculates delay_seconds and duration_seconds from a time range.
    Returns (delay_seconds, duration_seconds).
    """
    if now is None:
        now = datetime.now()

    start_dt = parse_time_string(start_str)
    end_dt = parse_time_string(end_str)

    # Ensure start/end match the reference date
    start_dt = datetime.combine(now.date(), start_dt.time())
    end_dt = datetime.combine(now.date(), end_dt.time())

    # If end is before start, assume end is tomorrow
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    # Logic for when to start
    if start_dt < now and end_dt > now:
        # We are already in the time range, start immediately
        delay_seconds = 0
        duration_seconds = max(1, int((end_dt - now).total_seconds()))
    elif start_dt >= now:
        # Start in the future
        delay_seconds = int((start_dt - now).total_seconds())
        duration_seconds = max(1, int((end_dt - start_dt).total_seconds()))
    else:
        # Both start and end in the past, assume tomorrow
        start_dt += timedelta(days=1)
        end_dt += timedelta(days=1)
        delay_seconds = int((start_dt - now).total_seconds())
        duration_seconds = max(1, int((end_dt - start_dt).total_seconds()))

    return delay_seconds, duration_seconds
