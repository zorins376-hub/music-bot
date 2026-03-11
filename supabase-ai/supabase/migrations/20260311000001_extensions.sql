-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 001: Extensions
-- Enable pgvector for embeddings, pg_cron for scheduled jobs
-- ═══════════════════════════════════════════════════════════════════════════════

create extension if not exists vector with schema extensions;
create extension if not exists pg_cron with schema extensions;
create extension if not exists pg_net  with schema extensions;
