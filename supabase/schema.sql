-- SedarWatchlist schema for Supabase Postgres.
-- Idempotent — safe to re-run as the project evolves.

create extension if not exists "pgcrypto";

-- ---------- watchlist ----------
create table if not exists public.watchlist (
    id           uuid primary key default gen_random_uuid(),
    user_id      text        not null,
    company_id   text,
    ticker       text,
    name         text        not null,
    sector       text,
    exchange     text,
    market_cap   numeric(20, 2),
    created_at   timestamptz not null default now()
);

alter table public.watchlist
    add column if not exists sedar_profile_id  text,
    add column if not exists sedar_profile_url text,
    add column if not exists jurisdiction      text;

-- Allow ticker to be null (SEDAR has issuers without an exchange-listed ticker).
alter table public.watchlist alter column ticker drop not null;

-- A user can only watch a given SEDAR issuer once.
create unique index if not exists watchlist_user_sedar_idx
    on public.watchlist (user_id, sedar_profile_id)
    where sedar_profile_id is not null;

create index if not exists watchlist_user_idx       on public.watchlist (user_id);
create index if not exists watchlist_created_at_idx on public.watchlist (created_at desc);

-- ---------- filings ----------
create table if not exists public.filings (
    id           uuid primary key default gen_random_uuid(),
    company_id   text,
    ticker       text,
    filing_type  text        not null,
    filing_date  date        not null,
    url          text        not null,
    created_at   timestamptz not null default now()
);

alter table public.filings
    add column if not exists sedar_profile_id text,
    add column if not exists sedar_filing_id  text,
    add column if not exists title            text,
    add column if not exists source           text default 'sedar_plus';

alter table public.filings alter column ticker drop not null;

-- Dedup: same SEDAR filing should never be inserted twice.
create unique index if not exists filings_sedar_unique_idx
    on public.filings (sedar_profile_id, sedar_filing_id)
    where sedar_profile_id is not null and sedar_filing_id is not null;

create index if not exists filings_sedar_profile_idx on public.filings (sedar_profile_id);
create index if not exists filings_ticker_idx        on public.filings (ticker);
create index if not exists filings_filing_date_idx   on public.filings (filing_date desc);
create index if not exists filings_created_at_idx    on public.filings (created_at desc);
