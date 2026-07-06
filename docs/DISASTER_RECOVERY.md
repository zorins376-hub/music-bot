# Disaster Recovery Runbook — BLACK ROOM music bot

_Last updated 2026-07-06. Keep this in sync when backup/infra changes._

## 1. What data exists and how critical it is

| Data | Where it lives | Criticality | Regenerable? |
|------|----------------|-------------|--------------|
| **Track catalog** (`tracks`: source_id, artist/title, metadata) | PostgreSQL | **CROWN JEWEL** | No — this is the durable index |
| **CDN message-id map** (`cdnmsg:*`) | Redis (persistent) | **HIGH** — the copy_message delivery handles | Rebuilds slowly as tracks play/prefetch |
| Hot pins, learned corrections, catalog:seed | Redis (persistent) | Medium | Partially (re-learned/re-seeded) |
| CDN audio | Telegram **cache channel** (`CACHE_CHANNEL_ID`) | HIGH — Telegram-hosted, permanent | No, but Telegram keeps it |
| file_id cache (`fid:*`) | Redis + `tracks.file_id` | **LOW** — local-Bot-API file_ids decay; self-heal re-downloads | Yes (re-download) |
| telegram-bot-api file store (volume) | Docker volume `telegram_bot_api_data` | **LOW** since copy_message migration (2026-07-06) | Yes — holds only ~dozens of recent files |
| Users, playlists, payments, history | PostgreSQL | High | No |

## 2. Backups (RPO ≈ 24h)

Three independent daily copies (all cron on the VPS, ~03:30–03:50 UTC):

1. **Local** `/root/db-backups/musicbot_backup_<UTC>.tar.gpg` — AES-256, 30-day retention. (`github-backup-musicbot.sh`)
2. **GitHub** private repo `git@github.com:3hp946/musicbot-backups.git` — same encrypted file, pushed via the deploy key `/root/db-backups/.deploy_key`. (`github-push-backup.sh`, cron `50 3`)
3. **Telegram DM** — plain `pg_dump` gz to the owner's bot DM. (`offsite-musicbot.sh`, cron `45 3`)

Each `.tar.gpg` contains `postgres.sql.gz` (full DB) + `redis_critical.json.gz` (`fid:*`, `cdnmsg:*`, `search:learn:*`, `hotpins`, `catalog:seed`, `cdn:posted`) + `RESTORE.txt`.

**Decryption passphrase**: in the owner's Telegram DM (sent 2026-07-05) and in `/root/db-backups/.gh_backup_pass` (root-only). **NOT** in any repo. Without it the encrypted backups are unrecoverable — keep it in a password manager.

## 3. Restore procedure

```bash
# 0. Get a backup + the passphrase.
gpg --batch --decrypt --passphrase '<PASSPHRASE>' -o backup.tar musicbot_backup_XXXX.tar.gpg
tar -xf backup.tar

# 1. PostgreSQL (the crown jewel — restore first)
gunzip -c postgres.sql.gz | docker exec -i music-bot-postgres-1 psql -U musicbot -d musicbot

# 2. Redis critical keys (cdnmsg map, hot pins, catalog:seed, learned, fid)
#    python: json.load(gzip.open('redis_critical.json.gz')) then:
#      fid/cdnmsg/learned: SET each key (fid honours its 'ttl')
#      hotpins/hotpins_hits: HSET mapping ; catalog_seed/cdn_posted: SADD ; (see RESTORE.txt)

# 3. Bring the stack up: cd /root/music-bot && docker compose up -d
```

## 4. Key facts / gotchas

- **Never delete the `telegram_bot_api_data` volume** — it holds the current instance's file store. (Low value now, but wiping it kills the remaining live file_ids.)
- **Delivery is self-healing**: dead file_ids re-download (`file_id_heal.send_or_heal`); popular tracks deliver instantly via `copy_message` from the CDN channel (`cdnmsg:*`). So a lost `fid:*` cache is not fatal.
- **The CDN channel is the real audio store** — as long as it and the `cdnmsg` map survive, delivery works.
- **Single server (Hetzner 5.75.182.82:2222) is the SPOF.** No hot standby. On total loss: provision a new host, restore Postgres + Redis from the latest backup, re-point DNS (`blackroom-music.duckdns.org`), redeploy `docker compose up -d`. The CDN channel + catalog survive; file_ids self-heal.
- **Secrets**: `.env` on the server is the source of truth (never in git). Supabase keys were rotated 2026-07 after a leak — see the security commit.
