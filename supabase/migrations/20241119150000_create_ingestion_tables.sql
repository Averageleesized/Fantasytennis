create extension if not exists citext with schema extensions;

-- Create reference tables for tours and surfaces
create table if not exists public.tours (
    id uuid primary key default gen_random_uuid(),
    slug citext not null unique,
    display_name text not null,
    governing_body text,
    gender text not null check (gender in ('men', 'women', 'mixed')),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.surfaces (
    id uuid primary key default gen_random_uuid(),
    slug citext not null unique,
    display_name text not null,
    pace_class text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

-- Source metadata for ingested payloads
create table if not exists public.ingest_sources (
    id uuid primary key default gen_random_uuid(),
    slug citext not null unique,
    name text not null,
    base_url text,
    description text,
    created_at timestamptz not null default timezone('utc', now())
);

-- Players captured from external feeds
create table if not exists public.ingest_players (
    id bigserial primary key,
    source_id uuid not null references public.ingest_sources(id) on delete cascade,
    external_id text not null,
    tour_id uuid not null references public.tours(id),
    full_name text not null,
    country_code char(3),
    handedness text,
    birthdate date,
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint ingest_players_source_external_key unique (source_id, external_id)
);

-- Tournament metadata captured during ingestion
create table if not exists public.ingest_tournaments (
    id bigserial primary key,
    source_id uuid not null references public.ingest_sources(id) on delete cascade,
    external_id text not null,
    tour_id uuid not null references public.tours(id),
    surface_id uuid references public.surfaces(id),
    season smallint not null,
    name text not null,
    location text,
    category text,
    start_date date,
    end_date date,
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint ingest_tournaments_source_external_key unique (source_id, external_id)
);

-- Ranking snapshots tied back to ingested players
create table if not exists public.ingest_rankings (
    id bigserial primary key,
    player_id bigint not null references public.ingest_players(id) on delete cascade,
    tour_id uuid not null references public.tours(id),
    ranking_date date not null,
    rank integer not null check (rank > 0),
    points integer not null default 0,
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    constraint ingest_rankings_player_date_key unique (player_id, ranking_date)
);

-- Helpful indexes for ingestion workflows
create index if not exists ingest_players_tour_id_idx on public.ingest_players (tour_id);
create index if not exists ingest_tournaments_tour_start_idx on public.ingest_tournaments (tour_id, start_date);
create index if not exists ingest_tournaments_surface_idx on public.ingest_tournaments (surface_id);
create index if not exists ingest_rankings_tour_date_idx on public.ingest_rankings (tour_id, ranking_date);
