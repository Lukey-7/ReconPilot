"""Check a day's uploaded files before anything runs (spec 7.2).

``validate_files`` reads the files the way the engine's ``storage.read_day``
will and reports, per file and row, everything that would make the run fail or
give a wrong answer. Errors block the run; warnings do not.

Row numbers are the file's line numbers with the header as row 1, so they
match the row a user sees when the file is opened in Excel.

Files exported from Excel often start with a UTF-8 byte-order mark and end
lines with CRLF; both are accepted. The stored bytes stay exactly as uploaded;
``engine_bytes`` gives the form ``read_day`` expects (no byte-order mark).
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from reconpilot.models import Side
from reconpilot.storage import FILES

FILE_KINDS: dict[str, str] = {kind: name for kind, name in FILES.items() if kind != "truth"}
REQUIRED: tuple[str, ...] = ("securities", "fx", "trades", "positions", "holdings", "cash", "fund")
OPTIONAL: tuple[str, ...] = tuple(kind for kind in FILE_KINDS if kind not in REQUIRED)
KIND_BY_FILENAME: dict[str, str] = {name: kind for kind, name in FILE_KINDS.items()}

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 200_000
MAX_ISSUES_PER_FILE = 100  # beyond this a file's issues are summarised in one line

# Exact headers, as storage.write_day writes them.
HEADERS: dict[str, list[str]] = {
    "securities": ["security_id", "name", "currency", "asset_class"],
    "fx": ["currency", "usd_per_unit"],
    "trades": ["trade_id", "trade_date", "settle_date", "security_id", "side", "quantity", "price",
               "currency", "fx_rate", "fees", "cash_amount"],
    "positions": ["security_id", "quantity", "price", "price_date", "currency"],
    "holdings": ["security_id", "quantity", "price", "currency"],
    "cash": ["entry_id", "value_date", "security_id", "reference", "description", "amount"],
    "fund": ["key", "value"],
    "prior_prices": ["security_id", "price"],
    "book_cash": ["reference", "value_date", "security_id", "description", "amount"],
    "accruals": ["accrual_date", "kind", "amount"],
}

# Column types. id: must not be blank. text: anything. date: YYYY-MM-DD. number: finite.
# positive: finite and above zero. side: BUY or SELL.
COLUMNS: dict[str, dict[str, str]] = {
    "securities": {"security_id": "id", "name": "text", "currency": "id", "asset_class": "text"},
    "fx": {"currency": "id", "usd_per_unit": "positive"},
    "trades": {"trade_id": "id", "trade_date": "date", "settle_date": "date", "security_id": "id",
               "side": "side", "quantity": "positive", "price": "number", "currency": "id",
               "fx_rate": "positive", "fees": "number", "cash_amount": "number"},
    "positions": {"security_id": "id", "quantity": "number", "price": "number", "price_date": "date",
                  "currency": "id"},
    "holdings": {"security_id": "id", "quantity": "number", "price": "number", "currency": "id"},
    "cash": {"entry_id": "id", "value_date": "date", "security_id": "text", "reference": "text",
             "description": "text", "amount": "number"},
    "prior_prices": {"security_id": "id", "price": "number"},
    "book_cash": {"reference": "text", "value_date": "date", "security_id": "text", "description": "text",
                  "amount": "number"},
    "accruals": {"accrual_date": "date", "kind": "text", "amount": "number"},
}

# fund.csv keys: required ones must hold a value; optional ones may be blank (read as 0).
FUND_REQUIRED_KEYS = ("as_of", "book_opening_cash", "custodian_opening_cash", "prior_nav_per_share",
                      "shares_outstanding", "accrued_expenses")
FUND_OPTIONAL_KEYS = ("management_fee_rate", "daily_expense_budget")

# Columns whose values must be unique within their file.
UNIQUE: dict[str, str] = {
    "securities": "security_id",
    "fx": "currency",
    "trades": "trade_id",
    "positions": "security_id",
    "holdings": "security_id",
    "cash": "entry_id",
    "prior_prices": "security_id",
}

ACCRUAL_KINDS = ("MANAGEMENT_FEE", "EXPENSES")
SIDES = tuple(s.value for s in Side)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Issue:
    file: str  # the file's name, e.g. "book_trades.csv"
    row: int | None  # line number with the header as row 1; None for the whole file
    message: str


@dataclass
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"errors": [asdict(i) for i in self.errors], "warnings": [asdict(i) for i in self.warnings]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ValidationReport:
        return cls([Issue(**i) for i in d.get("errors", [])], [Issue(**i) for i in d.get("warnings", [])])


# --------------------------------------------------------------------------- decoding


def decode_text(content: bytes) -> str:
    """UTF-8 text with any byte-order mark removed. Raises ``UnicodeDecodeError``."""
    return content.decode("utf-8-sig")


def engine_bytes(content: bytes) -> bytes:
    """``content`` as ``storage.read_day`` reads it: UTF-8 without a byte-order mark.

    Line endings are left alone; the engine's CSV reader accepts CRLF and LF.
    """
    return content[3:] if content.startswith(b"\xef\xbb\xbf") else content


# --------------------------------------------------------------------------- collecting issues


class _Collector:
    """Issues for a report, capped at ``MAX_ISSUES_PER_FILE`` per file and severity."""

    def __init__(self) -> None:
        self.report = ValidationReport()
        self._counts: Counter[tuple[str, str]] = Counter()

    def _add(self, target: list[Issue], severity: str, file: str, row: int | None, message: str) -> None:
        self._counts[(file, severity)] += 1
        if self._counts[(file, severity)] <= MAX_ISSUES_PER_FILE:
            target.append(Issue(file, row, message))

    def error(self, file: str, row: int | None, message: str) -> None:
        self._add(self.report.errors, "error", file, row, message)

    def warning(self, file: str, row: int | None, message: str) -> None:
        self._add(self.report.warnings, "warning", file, row, message)

    def finish(self) -> ValidationReport:
        for (file, severity), count in sorted(self._counts.items()):
            extra = count - MAX_ISSUES_PER_FILE
            if extra > 0:
                target = self.report.errors if severity == "error" else self.report.warnings
                target.append(Issue(file, None, f"... and {extra:,} more {severity}s in this file."))
        return self.report


# --------------------------------------------------------------------------- parsing one file


@dataclass
class _Row:
    line: int
    values: dict[str, str]


def _parse_number(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_date(value: str) -> date | None:
    if not _ISO_DATE.match(value or ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _check_value(kind_type: str, column: str, value: str) -> str | None:
    """The problem with ``value`` for a column of ``kind_type``, or None."""
    if kind_type == "text":
        return None
    if kind_type == "id":
        return f"{column} is blank." if not value.strip() else None
    if kind_type == "date":
        return None if _parse_date(value) else f"{column} {value!r} is not a date in YYYY-MM-DD form."
    if kind_type == "side":
        return None if value in SIDES else f"{column} {value!r} must be {' or '.join(SIDES)}."
    number = _parse_number(value)
    if number is None:
        return f"{column} {value!r} is not a number."
    if kind_type == "positive" and number <= 0:
        return f"{column} {value!r} must be greater than zero."
    return None


def _read_rows(kind: str, content: bytes, issues: _Collector) -> list[_Row] | None:
    """The file's data rows, or None when the file cannot be read (size, encoding, header, CSV syntax)."""
    name = FILE_KINDS[kind]
    if len(content) > MAX_FILE_BYTES:
        issues.error(name, None, f"File is {len(content) / 1024 / 1024:,.1f} MB; the limit is "
                                 f"{MAX_FILE_BYTES // 1024 // 1024} MB.")
        return None
    try:
        text = decode_text(content)
    except UnicodeDecodeError as exc:
        issues.error(name, None, f"File is not UTF-8 text (byte {exc.start + 1}). Save it as CSV UTF-8.")
        return None
    if "\x00" in text:
        issues.error(name, None, "File contains NUL characters; it is not a CSV text file.")
        return None

    reader = csv.reader(io.StringIO(text, newline=""))
    expected = HEADERS[kind]
    rows: list[_Row] = []
    try:
        header = next(reader, None)
        if header is None:
            issues.error(name, None, "File is empty; it needs at least the header row.")
            return None
        if header != expected:
            issues.error(name, 1, f"Header must be exactly {','.join(expected)} (found {','.join(header)}).")
            return None
        for values in reader:
            if not values:  # a blank line, which the engine's reader skips too
                continue
            if len(rows) >= MAX_ROWS:
                issues.error(name, None, f"File has more than {MAX_ROWS:,} rows.")
                return None
            line = reader.line_num
            if len(values) != len(expected):
                issues.error(name, line, f"Row has {len(values)} values; the header has {len(expected)}.")
                continue
            rows.append(_Row(line, dict(zip(expected, values))))
    except csv.Error as exc:
        issues.error(name, reader.line_num, f"CSV cannot be read: {exc}.")
        return None
    return rows


def _check_columns(kind: str, rows: list[_Row], issues: _Collector) -> list[_Row]:
    """Report bad values; return the rows whose values are all usable."""
    name = FILE_KINDS[kind]
    types = COLUMNS[kind]
    good = []
    for row in rows:
        problems = [p for col, t in types.items() if (p := _check_value(t, col, row.values[col]))]
        for p in problems:
            issues.error(name, row.line, p)
        if not problems:
            good.append(row)
    return good


def _check_unique(kind: str, rows: list[_Row], issues: _Collector) -> None:
    column = UNIQUE.get(kind)
    if column is None:
        return
    first: dict[str, int] = {}
    for row in rows:
        value = row.values[column]
        if value in first:
            issues.error(FILE_KINDS[kind], row.line, f"Duplicate {column} {value!r} (first on row {first[value]}).")
        else:
            first[value] = row.line


def _check_fund(rows: list[_Row], as_of: date, issues: _Collector) -> None:
    name = FILE_KINDS["fund"]
    values: dict[str, tuple[int, str]] = {}
    for row in rows:
        key, value = row.values["key"], row.values["value"]
        if key in values:
            issues.error(name, row.line, f"Duplicate key {key!r} (first on row {values[key][0]}).")
            continue
        values[key] = (row.line, value)
        if key not in FUND_REQUIRED_KEYS and key not in FUND_OPTIONAL_KEYS:
            issues.warning(name, row.line, f"Unknown key {key!r} is ignored.")

    for key in FUND_REQUIRED_KEYS:
        if key not in values:
            issues.error(name, None, f"Key {key!r} is missing.")
    for key in (*FUND_REQUIRED_KEYS, *FUND_OPTIONAL_KEYS):
        if key not in values or key == "as_of":
            continue
        line, value = values[key]
        if key in FUND_OPTIONAL_KEYS and not value.strip():
            continue
        number = _parse_number(value)
        if number is None:
            issues.error(name, line, f"{key} {value!r} is not a number.")
        elif key == "shares_outstanding" and number <= 0:
            issues.error(name, line, f"shares_outstanding {value!r} must be greater than zero.")

    if "as_of" in values:
        line, value = values["as_of"]
        file_date = _parse_date(value)
        if file_date is None:
            issues.error(name, line, f"as_of {value!r} is not a date in YYYY-MM-DD form.")
        elif file_date != as_of:
            issues.error(name, line, f"as_of is {file_date} but these files are being loaded for {as_of}.")


# --------------------------------------------------------------------------- the whole day


def validate_files(files: dict[str, bytes], as_of: date) -> ValidationReport:
    """Check one day's files, given as ``{kind: bytes}`` with kinds from ``FILE_KINDS``.

    Raises ``ValueError`` for a kind that is not in ``FILE_KINDS``.
    """
    unknown = sorted(set(files) - set(FILE_KINDS))
    if unknown:
        raise ValueError(f"unknown file kinds: {', '.join(unknown)}")
    issues = _Collector()

    for kind in REQUIRED:
        if kind not in files:
            issues.error(FILE_KINDS[kind], None, "Required file is missing.")
    for kind in OPTIONAL:
        if kind not in files:
            issues.warning(FILE_KINDS[kind], None, "Optional file not uploaded; the day runs without it.")

    raw: dict[str, list[_Row]] = {}  # every readable row, for the sets other files refer to
    parsed: dict[str, list[_Row]] = {}  # rows whose values are all usable
    for kind in FILE_KINDS:
        if kind not in files:
            continue
        rows = _read_rows(kind, files[kind], issues)
        if rows is None:
            continue
        if kind == "fund":
            _check_fund(rows, as_of, issues)
            continue
        _check_unique(kind, rows, issues)
        raw[kind] = rows
        parsed[kind] = _check_columns(kind, rows, issues)

    _check_references(raw, parsed, issues)
    return issues.finish()


def _check_references(raw: dict[str, list[_Row]], parsed: dict[str, list[_Row]], issues: _Collector) -> None:
    """Checks across files: known securities, FX for every currency, dates in order, accrual kinds.

    A security or currency counts as listed even if its own row has a bad value
    (already reported), so one bad cell does not cascade into errors elsewhere.
    """
    securities = {r.values["security_id"] for r in raw.get("securities", [])}
    rates = {r.values["currency"] for r in raw.get("fx", [])}

    if "securities" in raw:
        for kind in ("trades", "positions", "holdings", "cash", "book_cash"):
            for row in raw.get(kind, []):
                sid = row.values["security_id"]
                if sid.strip() and sid not in securities:
                    issues.error(FILE_KINDS[kind], row.line, f"Security {sid!r} is not in securities.csv.")
        for row in raw.get("prior_prices", []):
            sid = row.values["security_id"]
            if sid.strip() and sid not in securities:
                issues.warning(FILE_KINDS["prior_prices"], row.line,
                               f"Security {sid!r} is not in securities.csv; its prior price is not used.")

    if "fx" in raw:
        for kind in ("securities", "trades", "positions", "holdings"):
            missing: dict[str, int] = {}
            for row in raw.get(kind, []):
                ccy = row.values["currency"]
                if ccy.strip() and ccy not in rates and ccy not in missing:
                    missing[ccy] = row.line
            for ccy, line in missing.items():
                issues.error(FILE_KINDS[kind], line, f"Currency {ccy!r} has no rate in fx_rates.csv.")

    for row in parsed.get("trades", []):
        trade_date, settle_date = _parse_date(row.values["trade_date"]), _parse_date(row.values["settle_date"])
        if settle_date < trade_date:
            issues.error(FILE_KINDS["trades"], row.line,
                         f"Trade {row.values['trade_id']!r} settles on {settle_date}, before its trade date "
                         f"{trade_date}.")

    for row in raw.get("accruals", []):
        if row.values["kind"] not in ACCRUAL_KINDS:
            issues.warning(FILE_KINDS["accruals"], row.line,
                           f"Accrual kind {row.values['kind']!r} is not {' or '.join(ACCRUAL_KINDS)}; it counts "
                           "towards today's accruals but the accrual check cannot match it.")
