# Supabase sample upload readiness

Before uploading the first BEI sample file:

1. Configure `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in the Streamlit deployment secrets.
2. Do not commit either secret to Git.
3. Confirm the app sidebar reports persistent storage as configured and reachable.
4. Use exactly one small BEI Excel file for the first test.
5. After upload, verify:
   - `upload_ledger` contains exactly one new SHA-256 entry.
   - `stock_daily` contains the expected unique `(trade_date, stock_code)` rows.
   - `orderbook_snapshot` contains rows only when Bid/Offer fields exist in the source.
   - the Streamlit app can reload and still see the imported data.
6. Retry the exact same file only after checking the ledger; the application is designed to recognize an already committed Supabase upload by SHA-256.

The first sample should be treated as an integration test, not as the start of the full historical import.
