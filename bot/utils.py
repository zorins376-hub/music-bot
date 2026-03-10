"""Shared utility functions — eliminates duplicated helpers across modules."""


def fmt_duration(seconds: int | None) -> str:
    """Format seconds as m:ss string. Returns '-:--' for None or 0."""
    if seconds is None or seconds == 0:
        return "-:--"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def fmt_duration_ms(ms: int) -> str:
    """Format milliseconds as m:ss string."""
    return fmt_duration(ms // 1000)
