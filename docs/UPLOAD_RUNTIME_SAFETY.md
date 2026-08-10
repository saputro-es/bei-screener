# Upload runtime safety

The uploader keeps the selected files in the native Streamlit widget and never deletes or mutates existing historical data as part of UI feedback.

Successful persistence sets a session-state notice before the app reruns. The next render displays that notice so a successful upload, duplicate/repair, or persistence failure is visible after rerun.

The upload ledger remains SHA-256 based. Re-selecting an existing file does not create a new ledger entry; it enters historical repair mode.

Existing Supabase data is not migrated, reset, or deleted by the uploader UI fix.
