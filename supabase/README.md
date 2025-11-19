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
