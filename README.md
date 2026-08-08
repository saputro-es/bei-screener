# BEI Screener

Database-backed Indonesian stock screener for daily BEI Excel data.

## What it does

1. Accepts one or more `.xlsx`/`.xls` files.
2. Normalizes common BEI column names automatically.
3. Stores daily rows in local SQLite at `database/bei_screener.db`.
4. Upserts by `(trade_date, stock_code)` so re-uploading a day does not duplicate it.
5. Calculates **3-day Net Buy %** and keeps only stocks **above 65%** by default.
6. Shows the three individual daily percentages (D1/D2/D3).
7. Calculates SMA20, SMA50, RSI14, volume ratio, and ATR14 when enough history exists.
8. Classifies stocks as `LANJUT RALLY`, `KONSOLIDASI / KONFIRMASI`, or `BERISIKO` using transparent rule-based scoring.
9. Produces an indicative one-week target range and ATR-based stop-loss reference.

## Recommended data

For useful technical analysis, upload at least 50 trading days per stock. For the 3-day accumulation filter, at least the latest 3 trading rows with Foreign Buy and Foreign Sell are required.

Minimum required columns:

- `Kode Saham`
- `Tanggal Perdagangan Terakhir`

For accumulation:

- `Foreign Buy`
- `Foreign Sell`

For technical analysis:

- `Penutupan`
- ideally `Open Price`, `Tertinggi`, `Terendah`, and `Volume`

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Testing

```bash
pytest -q
```

GitHub Actions runs the test suite automatically on pushes and pull requests.

## Important

SQLite and uploaded market-data files are intentionally ignored by Git. The application recreates the database schema automatically on startup.
