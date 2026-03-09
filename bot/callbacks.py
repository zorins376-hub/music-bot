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


class FavoriteCb(CallbackData, prefix="fav"):
    """Favorites callback."""
    tid: int
    act: str  # add / del


class ShareTrackCb(CallbackData, prefix="shtr"):
    """Share track callback."""
    tid: int
    act: str  # mk / dl


class MixCb(CallbackData, prefix="mix"):
    """Daily mix callback actions."""
    act: str  # save
    sid: str
