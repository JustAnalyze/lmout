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


def format_duration_seconds(seconds: int) -> str:
    """
    Formats a duration in seconds into a human-readable string (e.g., '2h 30m' or '45m').
    """
    minutes = seconds // 60
    if minutes == 0 and seconds > 0: # Handle durations less than a minute
        return "<1m"
    elif minutes <= 60:
        return f"{minutes}m"
    else:
        hours = minutes // 60
        remaining_minutes = minutes % 60
        return f"{hours}h {remaining_minutes}m"


def calculate_from_range(
    start_str: str, end_str: str, now: datetime | None = None
) -> tuple[int, int, int]:
    """
    Calculates delay_seconds, duration_seconds (remaining), and total_duration_seconds from a time range.
    Returns (delay_seconds, duration_seconds, total_duration_seconds).
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

    total_duration_seconds = int((end_dt - start_dt).total_seconds())

    # Logic for when to start
    if start_dt < now and end_dt > now:
        # We are already in the time range, start immediately
        delay_seconds = 0
        duration_seconds = max(1, int((end_dt - now).total_seconds()))
    elif start_dt >= now:
        # Start in the future
        delay_seconds = int((start_dt - now).total_seconds())
        duration_seconds = total_duration_seconds
    else:
        # Both start and end in the past, assume tomorrow
        start_dt += timedelta(days=1)
        end_dt += timedelta(days=1)
        delay_seconds = int((start_dt - now).total_seconds())
        duration_seconds = total_duration_seconds

    return delay_seconds, duration_seconds, total_duration_seconds
