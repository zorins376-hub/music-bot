"""Run YouTube health probe on prod via SSH."""
import asyncio
import sys

sys.path.insert(0, "deploy")
from ssh_common import connect_ssh

PROBE = r"""cd /root/music-bot && docker compose exec -T bot python -c "
import asyncio
from bot.services.youtube_cookies import run_health_probe, validate_cookie_file, get_last_probe_status
async def main():
    v = validate_cookie_file()
    print('cookies_exists', v.get('exists'))
    print('cookies_valid', v.get('valid'))
    print('line_count', v.get('line_count'))
    print('auth_cookies', v.get('auth_cookies'))
    ok = await run_health_probe(notify_on_failure=False)
    print('probe_ok', ok)
    s = get_last_probe_status()
    print('probe_summary', s.get('summary'))
    if s.get('error'):
        print('probe_error', str(s.get('error'))[:400])
asyncio.run(main())
"
"""


def main():
    ssh = connect_ssh(timeout=60)
    _, stdout, stderr = ssh.exec_command(PROBE, timeout=180)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    print(out)
    if err.strip():
        print("stderr:", err[:2000])
    ssh.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
