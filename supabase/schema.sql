-- SedarWatchlist schema for Supabase Postgres.
-- Run this in the Supabase SQL editor (or psql) to provision the tables
-- consumed by the FastAPI backend.

create extension if not exists "pgcrypto";

create table if not exists public.watchlist (
    id           uuid primary key default gen_random_uuid(),
    user_id      text        not null,
    company_id   text,
    ticker       text        not null,
    name         text        not null,
    sector       text,
    exchange     text,
    market_cap   numeric(20, 2),
    created_at   timestamptz not null default now(),
    unique (user_id, ticker)
);

create index if not exists watchlist_user_idx       on public.watchlist (user_id);
create index if not exists watchlist_created_at_idx on public.watchlist (created_at desc);

create table if not exists public.filings (
    id           uuid primary key default gen_random_uuid(),
    company_id   text,
    ticker       text        not null,
    filing_type  text        not null,
    filing_date  date        not null,
    url          text        not null,
    created_at   timestamptz not null default now()
);

create index if not exists filings_ticker_idx      on public.filings (ticker);
create index if not exists filings_filing_date_idx on public.filings (filing_date desc);
create index if not exists filings_created_at_idx  on public.filings (created_at desc);
