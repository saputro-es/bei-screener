# Supabase migration history

The production Supabase migration history was reconciled with the versioned files in `supabase/migrations` after the repository and remote history drifted because migrations had been recorded with generated remote timestamps.

The database schema was not changed by the reconciliation; only `supabase_migrations.schema_migrations` history was aligned with the repository's canonical migration versions.
