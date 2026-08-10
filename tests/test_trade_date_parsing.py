import pandas as pd

from modules.database import normalize_dataframe


def _row(value):
    return {
        "Kode Saham": "TEST",
        "Tanggal Perdagangan Terakhir": value,
        "Penutupan": 100,
        "Foreign Buy": 700,
        "Foreign Sell": 300,
    }


def test_excel_serial_trade_date_normalizes_to_iso():
    # 2026-08-03 in Excel's 1900 date system.
    value = (pd.Timestamp("2026-08-03") - pd.Timestamp("1899-12-30")).days
    result = normalize_dataframe(pd.DataFrame([_row(value)]))
    assert result.loc[0, "trade_date"] == "2026-08-03"


def test_excel_serial_float_trade_date_normalizes_to_iso():
    value = float((pd.Timestamp("2026-08-03") - pd.Timestamp("1899-12-30")).days)
    result = normalize_dataframe(pd.DataFrame([_row(value)]))
    assert result.loc[0, "trade_date"] == "2026-08-03"


def test_existing_bei_string_formats_still_normalize():
    values = ["03/08/2026", "2026-08-03", "20260803"]
    result = normalize_dataframe(pd.DataFrame([_row(value) for value in values]))
    assert result["trade_date"].tolist() == ["2026-08-03"] * 3
