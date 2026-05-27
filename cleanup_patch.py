"""Final cleanup patches: filter perm-failed from search, lower expected-error log levels."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

# ──────────────────────────────────────────────────────────────────────────
# Fix 1: filter permanently_failed YouTube IDs from search results after dedup.
# Keep them if it would empty the result set (don't show "nothing found").
OLD_DEDUP = """    _dedup_limit = max(max_results, 15) if is_group else max_results
    results = deduplicate_results(all_results, lang_hint=script, query=provider_query)[:_dedup_limit] if all_results else []"""

NEW_DEDUP = """    _dedup_limit = max(max_results, 15) if is_group else max_results
    results = deduplicate_results(all_results, lang_hint=script, query=provider_query)[:_dedup_limit] if all_results else []

    # Filter out permanently-failed YouTube tracks (cached for 24h) — but only if
    # we'd still have results left. Otherwise keep them (user can still try).
    try:
        from bot.services.downloader import _is_permanently_failed as _pf_filter
        _filtered = [r for r in results if not _pf_filter(r.get("video_id", ""))]
        if _filtered:
            _removed = len(results) - len(_filtered)
            if _removed > 0:
                logger.info("Search: filtered %d permanently-failed track(s) from results", _removed)
            results = _filtered
    except Exception:
        logger.debug("perm-failed filter error", exc_info=True)"""

if NEW_DEDUP not in src:
    if OLD_DEDUP not in src:
        print("FATAL: dedup anchor not found")
        sys.exit(1)
    src = src.replace(OLD_DEDUP, NEW_DEDUP, 1)
    print("+ Filter permanently-failed tracks from search results")

# ──────────────────────────────────────────────────────────────────────────
# Fix 2: DM download error — demote to warning for expected/perm-failed errors
OLD_DM_ERR = '''        except Exception as e:
            err_msg = str(e)
            logger.error("Download error for %s: %s", video_id, err_msg)'''

NEW_DM_ERR = '''        except Exception as e:
            err_msg = str(e)
            _err_lower = err_msg.lower()
            _is_expected_err = any(p in _err_lower for p in (
                "permanently failed", "video unavailable",
                "this content isn", "this video is", "has been removed",
                "sign in to confirm your age", "geo restriction",
            ))
            if _is_expected_err:
                logger.warning("Download error for %s (expected): %s", video_id, err_msg)
            else:
                logger.error("Download error for %s: %s", video_id, err_msg)'''

if NEW_DM_ERR not in src:
    if OLD_DM_ERR not in src:
        print("FATAL: DM error anchor not found")
        sys.exit(1)
    src = src.replace(OLD_DM_ERR, NEW_DM_ERR, 1)
    print("+ Demoted expected download errors to warning level")

# ──────────────────────────────────────────────────────────────────────────
# Fix 3: also demote Group auto-play expected errors to warning
OLD_GRP_ERR = '''    except Exception as e:
        err_msg = str(e)
        logger.error("Group auto-play error for %s: %s", video_id, err_msg)
        if raise_on_error:
            raise'''

NEW_GRP_ERR = '''    except Exception as e:
        err_msg = str(e)
        _err_lower = err_msg.lower()
        _is_expected = any(p in _err_lower for p in (
            "permanently failed", "video unavailable",
            "this content isn", "this video is", "has been removed",
            "sign in to confirm your age",
        ))
        if _is_expected:
            logger.warning("Group auto-play unavailable for %s: %s", video_id, err_msg)
        else:
            logger.error("Group auto-play error for %s: %s", video_id, err_msg)
        if raise_on_error:
            raise'''

if NEW_GRP_ERR not in src:
    if OLD_GRP_ERR in src:
        src = src.replace(OLD_GRP_ERR, NEW_GRP_ERR, 1)
        print("+ Demoted expected group auto-play errors to warning level")
    else:
        print("- Group auto-play error anchor not found (skip)")

# Verify
import ast
ast.parse(src)

# Save
bak = TARGET.with_suffix(".py.bak3")
bak.write_text(orig)
TARGET.write_text(src)

print(f"\nPatched: {TARGET}")
print(f"Backup:  {bak}")
print(f"Size: {len(orig)} -> {len(src)}")
