"""
version.py — Bot version and changelog management.

When adding new features:
1. Increment VERSION (major.minor.patch)
2. Add entry to CHANGELOG with new version as key
3. Bot will automatically notify users on /start
"""

# Current bot version
VERSION = "1.1.0"

# Welcome message for new users (sent after captcha)
WELCOME_MESSAGE = """◌ <b>BLACK ROOM v1.0.0</b> — Официальный запуск! 🎉

🎵 <b>Поиск</b> — Яндекс, Spotify, VK, SoundCloud, YouTube
📻 <b>Радио</b> — TEQUILA LIVE · FULLMOON LIVE · AUTO MIX
🏆 <b>Чарты</b> — Apple Music, YouTube, Яндекс, Русское Радио, Europa+
🎙 <b>Shazam</b> — распознавание по голосовому/аудио/видео
◈ <b>AI DJ</b> — персональные рекомендации под твой вкус
▸ <b>Плейлисты</b> — создавай и делись с друзьями
🎦 <b>Видео</b> — клипы с YouTube (360p/480p/720p)
◎ <b>Инлайн</b> — @TSmymusicbot_bot в любом чате
💬 <b>Группы</b> — добавь бота в чат
🤝 <b>Рефералы</b> — приглашай друзей → бонус треки + Premium
◇ <b>Premium</b> — безлимитно, 320 kbps (150 Stars)

/start — главное меню
/faq — полное руководство
/referral — твоя реферальная ссылка"""

# Changelog: version -> list of changes
# Each entry: (emoji, description_key) - key refers to i18n string
CHANGELOG = {
    "1.1.0": [
        ("❤️", "changelog_favorites"),
        ("📤", "changelog_share_tracks_mix"),
        ("✦", "changelog_daily_mix"),
        ("🆕", "changelog_release_radar"),
        ("🏆", "changelog_chart_bulk"),
        ("⚡", "changelog_chart_cache"),
    ],
    "1.0.0": [
        ("🎵", "changelog_search"),          # Поиск треков по 5 источникам
        ("📻", "changelog_radio"),            # Радио-каналы TEQUILA/FULLMOON
        ("🏆", "changelog_charts"),           # Чарты (Apple, YouTube, Яндекс, Русское Радио, Europa+)
        ("🎙", "changelog_recognize"),        # Распознавание (Shazam)
        ("◈", "changelog_recommend"),         # AI DJ рекомендации
        ("▸", "changelog_playlist"),          # Плейлисты
        ("🎦", "changelog_video"),            # Видеоклипы
        ("◎", "changelog_inline"),            # Инлайн-режим
        ("💬", "changelog_groups"),           # Поддержка групп
        ("◇", "changelog_premium"),           # Premium подписка
    ],
}

# Template for future updates:
# "1.1.0": [
#     ("🆕", "changelog_new_feature"),
# ],


def get_changelog_text(lang: str, version: str) -> str:
    """Get formatted changelog for a specific version."""
    from bot.i18n import t
    
    if version not in CHANGELOG:
        return ""
    
    lines = [f"<b>v{version}</b>\n"]
    for emoji, key in CHANGELOG[version]:
        text = t(lang, key)
        if text != key:  # Key exists in i18n
            lines.append(f"{emoji} {text}")
        else:
            lines.append(f"{emoji} {key}")
    
    return "\n".join(lines)


def get_new_features(lang: str, last_seen: str | None) -> str:
    """Get all features added since last_seen version.
    
    Returns formatted string with all new features, or empty if up to date.
    """
    from bot.i18n import t
    from packaging.version import Version
    
    if not last_seen:
        # First time user — don't spam with full changelog
        return ""
    
    try:
        last_v = Version(last_seen)
    except Exception:
        last_v = Version("0.0.0")
    
    current_v = Version(VERSION)
    if last_v >= current_v:
        return ""  # Up to date
    
    # Collect all new versions
    new_versions = []
    for ver in CHANGELOG:
        try:
            if Version(ver) > last_v:
                new_versions.append(ver)
        except Exception:
            continue
    
    if not new_versions:
        return ""
    
    # Sort newest first
    new_versions.sort(key=lambda v: Version(v), reverse=True)
    
    header = t(lang, "whats_new")
    parts = [f"<b>{header}</b>\n"]
    
    for ver in new_versions[:3]:  # Show max 3 versions
        parts.append(get_changelog_text(lang, ver))
        parts.append("")
    
    return "\n".join(parts).strip()
