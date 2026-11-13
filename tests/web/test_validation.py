"""Validation of a day's files before any run (spec 7.2)."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest

from reconpilot.storage import read_day
from reconpilot_web.validation import (
    FILE_KINDS,
    MAX_FILE_BYTES,
    MAX_ISSUES_PER_FILE,
    REQUIRED,
    engine_bytes,
    validate_files,
)

from .conftest import FUND_START

DAY1 = FUND_START


def _rows(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))


def _csv(rows: list[list[str]]) -> bytes:
    out = io.StringIO(newline="")
    csv.writer(out).writerows(rows)
    return out.getvalue().encode("utf-8")


def _edit(files: dict[str, bytes], kind: str, row: int, column: str, value: str) -> dict[str, bytes]:
    """A copy of ``files`` with one cell changed (``row`` 1 is the first data row)."""
    rows = _rows(files[kind])
    rows[row][rows[0].index(column)] = value
    return {**files, kind: _csv(rows)}


def _messages(issues) -> list[str]:
    return [f"{i.file}:{i.row}:{i.message}" for i in issues]


def test_valid_day_passes(day_files):
    report = validate_files(day_files[0], DAY1)
    assert report.ok, _messages(report.errors)
    assert report.errors == [] and report.warnings == []


def test_missing_required_file(day_files):
    files = {k: v for k, v in day_files[0].items() if k != "positions"}
    report = validate_files(files, DAY1)
    assert not report.ok
    assert [(i.file, i.row, i.message) for i in report.errors] == [
        ("book_positions.csv", None, "Required file is missing."),
    ]


def test_missing_optional_file_is_a_warning(day_files):
    files = {k: v for k, v in day_files[0].items() if k != "accruals"}
    report = validate_files(files, DAY1)
    assert report.ok
    assert [i.file for i in report.warnings] == ["accruals.csv"]


def test_wrong_header(day_files):
    rows = _rows(day_files[0]["trades"])
    rows[0][rows[0].index("quantity")] = "qty"
    report = validate_files({**day_files[0], "trades": _csv(rows)}, DAY1)
    assert len(report.errors) == 1
    issue = report.errors[0]
    assert (issue.file, issue.row) == ("book_trades.csv", 1)
    assert "Header must be exactly" in issue.message and "qty" in issue.message


def test_as_of_mismatch(day_files):
    report = validate_files(day_files[0], date(2026, 11, 10))
    assert [(i.file, i.message) for i in report.errors] == [
        ("fund.csv", "as_of is 2026-11-09 but these files are being loaded for 2026-11-10."),
    ]


def test_unknown_security(day_files):
    files = _edit(day_files[0], "trades", 1, "security_id", "XX0000000000")
    report = validate_files(files, DAY1)
    assert _messages(report.errors) == ["book_trades.csv:2:Security 'XX0000000000' is not in securities.csv."]


def test_duplicate_trade_id(day_files):
    rows = _rows(day_files[0]["trades"])
    rows[2][0] = rows[1][0]
    report = validate_files({**day_files[0], "trades": _csv(rows)}, DAY1)
    assert _messages(report.errors) == [f"book_trades.csv:3:Duplicate trade_id {rows[1][0]!r} (first on row 2)."]


def test_duplicate_entry_id(day_files):
    rows = _rows(day_files[0]["cash"])
    rows[3][0] = rows[1][0]
    report = validate_files({**day_files[0], "cash": _csv(rows)}, DAY1)
    assert _messages(report.errors) == [f"custodian_cash.csv:4:Duplicate entry_id {rows[1][0]!r} (first on row 2)."]


def test_settle_before_trade(day_files):
    rows = _rows(day_files[0]["trades"])
    header = rows[0]
    trade_date = date.fromisoformat(rows[1][header.index("trade_date")])
    rows[1][header.index("settle_date")] = str(trade_date - timedelta(days=1))
    report = validate_files({**day_files[0], "trades": _csv(rows)}, DAY1)
    assert len(report.errors) == 1
    assert report.errors[0].row == 2 and "before its trade date" in report.errors[0].message


def test_currency_without_fx_rate(day_files):
    rows = [r for r in _rows(day_files[0]["fx"]) if r[0] != "EUR"]
    report = validate_files({**day_files[0], "fx": _csv(rows)}, DAY1)
    assert report.errors
    assert all("Currency 'EUR' has no rate in fx_rates.csv." == i.message for i in report.errors)
    assert {i.file for i in report.errors} >= {"securities.csv"}


def test_bad_values_reported_per_row(day_files):
    files = _edit(day_files[0], "trades", 1, "quantity", "abc")
    files = _edit(files, "trades", 2, "trade_date", "13/11/2026")
    files = _edit(files, "trades", 3, "side", "HOLD")
    files = _edit(files, "positions", 1, "price", "nan")
    files = _edit(files, "fx", 1, "usd_per_unit", "0")
    assert _messages(validate_files(files, DAY1).errors) == [
        "fx_rates.csv:2:usd_per_unit '0' must be greater than zero.",
        "book_trades.csv:2:quantity 'abc' is not a number.",
        "book_trades.csv:3:trade_date '13/11/2026' is not a date in YYYY-MM-DD form.",
        "book_trades.csv:4:side 'HOLD' must be BUY or SELL.",
        "book_positions.csv:2:price 'nan' is not a number.",
    ]


def test_row_with_wrong_number_of_values(day_files):
    rows = _rows(day_files[0]["holdings"])
    rows[1] = rows[1][:-1]
    report = validate_files({**day_files[0], "holdings": _csv(rows)}, DAY1)
    assert _messages(report.errors) == ["custodian_holdings.csv:2:Row has 3 values; the header has 4."]


def test_fund_file_keys(day_files):
    rows = [r for r in _rows(day_files[0]["fund"]) if r[0] != "shares_outstanding"]
    rows.append(["mystery", "1"])
    report = validate_files({**day_files[0], "fund": _csv(rows)}, DAY1)
    assert [i.message for i in report.errors] == ["Key 'shares_outstanding' is missing."]
    assert [i.message for i in report.warnings] == ["Unknown key 'mystery' is ignored."]


def test_bom_and_crlf_accepted(day_files, tmp_path):
    """A file saved by Excel as "CSV UTF-8" starts with a byte-order mark and ends lines with CRLF."""
    excel = {}
    for kind, content in day_files[0].items():
        text = content.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
        excel[kind] = b"\xef\xbb\xbf" + text.encode("utf-8")
    assert all(b"\r\n" in c and c.startswith(b"\xef\xbb\xbf") for c in excel.values())
    report = validate_files(excel, DAY1)
    assert report.ok, _messages(report.errors)
    assert report.warnings == []

    # And the engine reads the same day from them.
    for kind, content in excel.items():
        (tmp_path / FILE_KINDS[kind]).write_bytes(engine_bytes(content))
    original = tmp_path / "original"
    original.mkdir()
    for kind, content in day_files[0].items():
        (original / FILE_KINDS[kind]).write_bytes(content)
    assert read_day(tmp_path) == read_day(original)


def test_not_utf8_and_empty_files(day_files):
    files = {**day_files[0], "securities": "security_id,name\n\xe9".encode("latin-1"), "fx": b""}
    messages = [(i.file, i.message) for i in validate_files(files, DAY1).errors]
    assert ("securities.csv", "File is not UTF-8 text (byte 18). Save it as CSV UTF-8.") in messages
    assert ("fx_rates.csv", "File is empty; it needs at least the header row.") in messages


def test_size_and_issue_limits(day_files):
    big = day_files[0]["prior_prices"] + b"X" * MAX_FILE_BYTES
    report = validate_files({**day_files[0], "prior_prices": big}, DAY1)
    assert [i.file for i in report.errors] == ["prior_prices.csv"]
    assert "limit is 5 MB" in report.errors[0].message

    rows = _rows(day_files[0]["book_cash"])[:1] + [["R", "not a date", "", "", "1"]] * (MAX_ISSUES_PER_FILE + 7)
    report = validate_files({**day_files[0], "book_cash": _csv(rows)}, DAY1)
    assert len(report.errors) == MAX_ISSUES_PER_FILE + 1
    assert report.errors[-1].message == "... and 7 more errors in this file."


def test_required_kinds():
    assert REQUIRED == ("securities", "fx", "trades", "positions", "holdings", "cash", "fund")
    assert "truth" not in FILE_KINDS
    with pytest.raises(ValueError):
        validate_files({"truth": b"[]"}, DAY1)
