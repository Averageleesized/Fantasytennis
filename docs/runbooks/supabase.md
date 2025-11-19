# Supabase provisioning runbook

Fantasytennis relies on a Supabase backend. The project already exists (see the credentials below), but these instructions capture everything needed to rotate credentials or recreate the environment from scratch.

## 1. Project status
The Supabase project for Fantasytennis already exists. Use the credentials below whenever you need to connect locally or from CI/CD:

| Variable | Value |
| --- | --- |
| `SUPABASE_URL` | https://ccntciicqpyvbmqppmne.supabase.co |
| `SUPABASE_ANON_KEY` | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNjbnRjaWljcXB5dmJtcXBwbW5lIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE4NjIyNTAsImV4cCI6MjA3NzQzODI1MH0.KsHYwwsD56OpHPJI5ptXui-kUmX7Jga9OqaBv-BLi0A` |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNjbnRjaWljcXB5dmJtcXBwbW5lIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MTg2MjI1MCwiZXhwIjoyMDc3NDM4MjUwfQ.d1nkU03u_V7bKIyO0qFkY8IXkNl2-3SFTu1xqUG7wok` |
| `SUPABASE_DB_PASSWORD` | `H9!rXqE7$2pL@uV5zN#kW3tC` |

Keep the table above up to date if the keys are rotated. The password powers any Postgres connection strings you build (see `.env.example`).

## 2. Re-create or rotate the project
If the existing project ever needs to be recreated:
1. Sign in at https://app.supabase.com/ and click **New project**.
2. Provide a project name such as `fantasytennis-prod` and select the desired region.
3. Choose a strong database password; Supabase will provision the database cluster. Record the password because it is only shown once.
4. After the project is ready, open **Project settings → API** and copy:
   - `Project URL`
   - `anon public` key
   - `service_role` key

## 3. Store local environment variables
Create a `.env` file in the repo root (the `.env.example` file shows all required keys):

```
cp .env.example .env
```

Fill in the values gathered in step 1.

## 4. Configure the Supabase CLI (local developers)
1. Install the CLI: `npm install -g supabase`.
   - This step currently fails inside the hosted execution environment due to a `403 Forbidden` npm registry restriction, but it will work on a normal development workstation.
2. From the backend root of this repository run `supabase init` to generate the local config and link the CLI to the project.
3. Commit the generated `supabase/config.toml` (excluding any secrets) so all developers share the same settings.

## 5. Deployment secrets
Add the same variables to your deployment platform's secret manager so CI/CD jobs can connect:

| Secret name | Value |
|-------------|-------|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_ANON_KEY` | anon public key |
| `SUPABASE_SERVICE_ROLE_KEY` | service role key |
| `SUPABASE_DB_PASSWORD` | database password |

For platforms that expect database connection strings, create `SUPABASE_DB_CONNECTION` using the template in `.env.example`.

## 6. Sharing with the team
Publish these instructions (or link to this file) in your internal documentation hub so future contributors can repeat the setup without exposing the raw credentials in Git.
