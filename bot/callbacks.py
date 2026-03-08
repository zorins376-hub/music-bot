"""Shared CallbackData definitions — breaks circular imports between handlers."""

from aiogram.filters.callback_data import CallbackData


class TrackCallback(CallbackData, prefix="t"):
    sid: str  # session ID
    i: int    # result index


class FeedbackCallback(CallbackData, prefix="fb"):
    tid: int    # track DB id
    act: str    # like / dislike


class AddToPlCb(CallbackData, prefix="apl"):
    """Add to playlist callback."""
    tid: int   # track DB id
    pid: int = 0   # playlist id (0 = pick playlist)


class QueueCb(CallbackData, prefix="q"):
    """Queue action callback."""
    act: str  # next / shuf / clr / show


class AddToQueueCb(CallbackData, prefix="aq"):
    """Add track to queue callback."""
    tid: int  # track DB id


class LyricsCb(CallbackData, prefix="lyr"):
    """Lyrics callback."""
    tid: int  # track DB id
