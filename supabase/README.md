# Supabase workflows

## Linking the remote project

The Supabase project uses a pooled Postgres endpoint that requires TLS. If you see an error like:

```
failed to connect to postgres: failed to connect to `host=aws-1-us-east-1.pooler.supabase.com user=postgres.ccntciicqpyvbmqppmne database=postgres`: failed SASL auth (expected AuthenticationSASLFinal message but received unexpected message *pgproto3.AuthenticationSASL)
```

run `supabase link` with SSL enabled so the CLI negotiates the correct authentication method:

```
SUPABASE_DB_PASSWORD=VM6eExACr1pQKC5B supabase link --project-ref ccntciicqpyvbmqppmne --use-ssl
```

If you prefer not to inline the password, export it first:

```
export SUPABASE_DB_PASSWORD=VM6eExACr1pQKC5B
supabase link --project-ref ccntciicqpyvbmqppmne --use-ssl
```

Once linked, you can run `supabase db diff --linked`, `supabase db push`, and `supabase db seed` as usual.

## API-Tennis ingestion

The ingestion script pulls players, tournaments, and rankings from the API-Tennis
service and upserts them into the `ingest_sources`, `ingest_players`,
`ingest_tournaments`, and `ingest_rankings` tables using the existing unique
constraints.

Required environment variables:

- `API_TENNIS_KEY`: API key used to authenticate with the API-Tennis service. Defaults to the provided key `db53a535d63fe359cdaa1488d15f3e55e12835c85590c4e3eace0dcc43edb4ab` if not set.
- `API_TENNIS_BASE_URL` (optional): Base URL for the API-Tennis endpoints. Defaults to `https://api.api-tennis.com/tennis`.
- `API_TENNIS_KEY`: API key used to authenticate with the API-Tennis service.
- `API_TENNIS_BASE_URL` (optional): Base URL for the API-Tennis endpoints. Defaults to `https://api-tennis.example.com`.
- `API_TENNIS_KEY_HEADER` (optional): HTTP header name for the API key. Defaults to `x-api-key`.
- `SUPABASE_URL`: Your project's Supabase REST URL.
- `SUPABASE_SERVICE_ROLE_KEY`: Service role key used to perform upserts via Supabase REST.

The script requires only Python 3 (it uses the standard library HTTP client).
The script requires Python 3 and the `requests` package (`pip install requests`).
Run the ingestion script with:

```bash
python scripts/ingest_api_tennis.py --print-summary
```

The `--print-summary` flag outputs a JSON summary of the ingestion run, including
the source identifier and how many players were ingested.

To fetch and print future tournaments from the API-Tennis `get_events` endpoint
without touching Supabase, run:

```bash
python scripts/ingest_api_tennis.py --list-future-tournaments
```
