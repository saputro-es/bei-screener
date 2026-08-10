from __future__ import annotations

import re
from datetime import date

import pandas as pd


FILENAME_DATE_RE = re.compile(r"(?:^|[-_])(20\d{2})(\d{2})(\d{2})(?:\.[^.]+)?$")


def expected_trade_date_from_filename(filename: str) -> str | None:
    """Extract YYYYMMDD from the canonical Ringkasan Saham filename."""
    match = FILENAME_DATE_RE.search(str(filename).strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def pin_trade_date_to_filename(raw: pd.DataFrame, filename: str) -> pd.DataFrame:
    """Resolve ambiguous Excel text dates using the filename as the authoritative date.

    BEI export files have historically contained ambiguous slash-formatted text dates.
    Parsing them with a global dayfirst=True rule can turn a July 6 file into June 7.
    The filename is unambiguous (YYYYMMDD), so we only pin the date when the source
    date column is uniformly parseable and at least one conventional interpretation
    matches the filename. If neither interpretation matches, fail closed rather than
    silently writing a wrong trading date.
    """
    expected = expected_trade_date_from_filename(filename)
    if expected is None or "trade_date" not in raw.columns:
        return raw

    data = raw.copy()
    values = data["trade_date"]
    parsed_default = pd.to_datetime(values, errors="coerce", dayfirst=False)
    parsed_dayfirst = pd.to_datetime(values, errors="coerce", dayfirst=True)
    expected_ts = pd.Timestamp(expected)

    default_match = parsed_default.notna() & (parsed_default.dt.normalize() == expected_ts)
    dayfirst_match = parsed_dayfirst.notna() & (parsed_dayfirst.dt.normalize() == expected_ts)

    if bool(default_match.all()):
        data["trade_date"] = expected
        return data
    if bool(dayfirst_match.all()):
        data["trade_date"] = expected
        return data

    # Excel-native datetime values should be unambiguous; accept them only when
    # they already agree with the filename. Otherwise reject the batch explicitly.
    if bool(parsed_default.notna().all()) and bool((parsed_default.dt.normalize() == expected_ts).all()):
        data["trade_date"] = expected
        return data

    raise ValueError(
        f"Tanggal file {filename} tidak konsisten dengan nama file. "
        f"Tanggal perdagangan yang diharapkan: {expected}. "
        "Upload dihentikan agar tidak menulis histori pada tanggal yang salah."
    )
