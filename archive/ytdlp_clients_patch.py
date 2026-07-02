"""Use multiple YouTube player clients for better availability."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/services/downloader.py")
src = TARGET.read_text()
orig = src

# Replace single-client config with multi-client. Order matters:
# 1. tv_embedded — bypasses many age-restrictions and "content unavailable"
# 2. web — standard, most reliable for music
# 3. android — strong fallback, often works when web fails
# 4. ios — another reliable fallback
# 5. mweb — has PO Token support (last because it's the most restricted)
OLD = '''    opts["extractor_args"] = {
        "youtube": {"player_client": ["mweb"]},
        "youtubepot-bgutilhttp": {"base_url": ["http://bgutil-provider:4416"]},
    }'''

NEW = '''    opts["extractor_args"] = {
        "youtube": {
            # Multi-client fallback: yt-dlp tries each until one succeeds.
            # tv_embedded / web / android / ios bypass many "content unavailable"
            # errors; mweb gets PO Token from bgutil-provider as final fallback.
            "player_client": ["tv_embedded", "web", "android", "ios", "mweb"],
        },
        "youtubepot-bgutilhttp": {"base_url": ["http://bgutil-provider:4416"]},
    }'''

if NEW in src:
    print("Already applied")
    sys.exit(0)
if OLD not in src:
    print("FATAL: anchor not found")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak3")
bak.write_text(orig)
TARGET.write_text(src)
print(f"+ player_client: ['mweb'] -> ['tv_embedded', 'web', 'android', 'ios', 'mweb']")
print(f"Patched: {TARGET}")
print(f"Backup:  {bak}")
