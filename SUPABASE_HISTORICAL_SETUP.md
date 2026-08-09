# Supabase Historical Persistence

BEI Screener keeps SQLite as the runtime/read path and mirrors the complete historical dataset into Supabase as the durable historical layer. GitHub Release backup remains an optional secondary recovery copy.

## 1. Apply the schema

Run these migrations in order in the Supabase SQL Editor:

1. `supabase/migrations/20260808000000_create_historical_bei_screener.sql`
2. `supabase/migrations/20260809000000_add_historical_persistence_rpc.sql`

The second migration exposes only `persist_bei_historical_batch(...)` to `service_role`. It is additive and contains no DROP/TRUNCATE/DELETE statements.

## 2. Configure Streamlit Secrets

Required for Supabase historical persistence:

```toml
SUPABASE_URL = "https://<project-ref>.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
```

For older projects the legacy server-side key is also accepted:

```toml
SUPABASE_SERVICE_ROLE_KEY = "..."
```

Do not put a secret key in source code or client-side code.

## 3. Runtime flow

```text
Excel upload
   ↓
normalize + validate
   ↓
SQLite transaction (runtime database)
   ↓
Supabase historical mirror
   ├─ stock_daily
   ├─ orderbook_snapshot
   ├─ technical_indicator_snapshot
   └─ upload_ledger
   ↓
optional GitHub Release SQLite backup
```

The Supabase mirror uses a deterministic canonical run UUID and upserts the same historical rows on retry. It never deletes older historical rows.

## 4. Large datasets

SQLite history is sent to Supabase in chunks of 2,000 daily rows. This avoids sending one oversized JSON request for a large BEI history.

## 5. Security

The application uses a server-side Supabase secret key. Public/anonymous roles are not granted execution rights for the persistence RPC. RLS remains enabled on the historical tables.

## 6. Verification

After applying the migrations and configuring secrets, upload one small BEI file. The app should complete the SQLite write and then the Supabase mirror. The repository CI must pass `compileall` and `pytest` before the feature is promoted.
