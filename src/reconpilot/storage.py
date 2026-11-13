"""Read and write a day's files as CSV, and cases as JSON."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from reconpilot.models import (
    Accrual,
    BookCashEntry,
    Case,
    CashLine,
    Category,
    DayData,
    Holding,
    PlantedBreak,
    Position,
    Security,
    Side,
    Trade,
)

FILES = {
    "securities": "securities.csv",
    "fx": "fx_rates.csv",
    "trades": "book_trades.csv",
    "positions": "book_positions.csv",
    "holdings": "custodian_holdings.csv",
    "cash": "custodian_cash.csv",
    "fund": "fund.csv",
    "truth": "planted_breaks.json",
    # Optional files; older data folders without them still load.
    "prior_prices": "prior_prices.csv",
    "book_cash": "book_cash.csv",
    "accruals": "accruals.csv",
}


def _write(path: Path, header: list[str], rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_day(day: DayData, folder: str | Path, truth: list[PlantedBreak] | None = None) -> Path:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    _write(out / FILES["securities"], ["security_id", "name", "currency", "asset_class"],
           [(s.security_id, s.name, s.currency, s.asset_class) for s in day.securities.values()])
    _write(out / FILES["fx"], ["currency", "usd_per_unit"], sorted(day.fx_rates.items()))
    _write(out / FILES["trades"],
           ["trade_id", "trade_date", "settle_date", "security_id", "side", "quantity", "price",
            "currency", "fx_rate", "fees", "cash_amount"],
           [(t.trade_id, t.trade_date, t.settle_date, t.security_id, t.side.value, t.quantity, t.price,
             t.currency, t.fx_rate, t.fees, t.cash_amount) for t in day.book_trades])
    _write(out / FILES["positions"], ["security_id", "quantity", "price", "price_date", "currency"],
           [(p.security_id, p.quantity, p.price, p.price_date, p.currency) for p in day.book_positions.values()])
    _write(out / FILES["holdings"], ["security_id", "quantity", "price", "currency"],
           [(h.security_id, h.quantity, h.price, h.currency) for h in day.custodian_holdings.values()])
    _write(out / FILES["cash"], ["entry_id", "value_date", "security_id", "reference", "description", "amount"],
           [(c.entry_id, c.value_date, c.security_id, c.reference, c.description, c.amount)
            for c in day.custodian_cash])
    _write(out / FILES["fund"], ["key", "value"], [
        ("as_of", day.as_of),
        ("book_opening_cash", day.book_opening_cash),
        ("custodian_opening_cash", day.custodian_opening_cash),
        ("prior_nav_per_share", day.prior_nav_per_share),
        ("shares_outstanding", day.shares_outstanding),
        ("accrued_expenses", day.accrued_expenses),
        ("management_fee_rate", day.management_fee_rate),
        ("daily_expense_budget", day.daily_expense_budget),
    ])
    _write(out / FILES["prior_prices"], ["security_id", "price"], sorted(day.prior_prices.items()))
    _write(out / FILES["book_cash"], ["reference", "value_date", "security_id", "description", "amount"],
           [(e.reference, e.value_date, e.security_id, e.description, e.amount) for e in day.book_cash])
    _write(out / FILES["accruals"], ["accrual_date", "kind", "amount"],
           [(a.accrual_date, a.kind, a.amount) for a in day.accruals])
    if truth is not None:
        (out / FILES["truth"]).write_text(
            json.dumps([{**asdict(p), "category": p.category.value} for p in truth], indent=2, default=str),
            encoding="utf-8",
        )
    return out


def read_day(folder: str | Path) -> DayData:
    src = Path(folder)
    d = date.fromisoformat
    fund = {r["key"]: r["value"] for r in _read(src / FILES["fund"])}
    securities = {
        r["security_id"]: Security(r["security_id"], r["name"], r["currency"], r.get("asset_class") or "EQUITY")
        for r in _read(src / FILES["securities"])
    }
    fx = {r["currency"]: float(r["usd_per_unit"]) for r in _read(src / FILES["fx"])}
    trades = [
        Trade(r["trade_id"], d(r["trade_date"]), d(r["settle_date"]), r["security_id"], Side(r["side"]),
              float(r["quantity"]), float(r["price"]), r["currency"], float(r["fx_rate"]), float(r["fees"]))
        for r in _read(src / FILES["trades"])
    ]
    positions = {
        r["security_id"]: Position(r["security_id"], float(r["quantity"]), float(r["price"]),
                                   d(r["price_date"]), r["currency"])
        for r in _read(src / FILES["positions"])
    }
    holdings = {
        r["security_id"]: Holding(r["security_id"], float(r["quantity"]), float(r["price"]), r["currency"])
        for r in _read(src / FILES["holdings"])
    }
    cash = [
        CashLine(r["entry_id"], d(r["value_date"]), r["security_id"], r["reference"], r["description"],
                 float(r["amount"]))
        for r in _read(src / FILES["cash"])
    ]
    return DayData(
        as_of=d(fund["as_of"]),
        securities=securities,
        fx_rates=fx,
        book_trades=trades,
        book_positions=positions,
        custodian_holdings=holdings,
        custodian_cash=cash,
        book_opening_cash=float(fund["book_opening_cash"]),
        custodian_opening_cash=float(fund["custodian_opening_cash"]),
        prior_nav_per_share=float(fund["prior_nav_per_share"]),
        shares_outstanding=float(fund["shares_outstanding"]),
        accrued_expenses=float(fund["accrued_expenses"]),
        management_fee_rate=float(fund.get("management_fee_rate", 0) or 0),
        daily_expense_budget=float(fund.get("daily_expense_budget", 0) or 0),
        prior_prices={r["security_id"]: float(r["price"]) for r in _optional(src / FILES["prior_prices"])},
        book_cash=[
            BookCashEntry(r["reference"], d(r["value_date"]), r["security_id"], r["description"], float(r["amount"]))
            for r in _optional(src / FILES["book_cash"])
        ],
        accruals=[Accrual(d(r["accrual_date"]), r["kind"], float(r["amount"]))
                  for r in _optional(src / FILES["accruals"])],
    )


def _optional(path: Path) -> list[dict]:
    return _read(path) if path.exists() else []


def read_truth(folder: str | Path) -> list[PlantedBreak]:
    path = Path(folder) / FILES["truth"]
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        PlantedBreak(
            Category(r["category"]), r["security_id"], r["detail"],
            date.fromisoformat(r["start"]) if r.get("start") else None,
            date.fromisoformat(r["fix"]) if r.get("fix") else None,
        )
        for r in raw
    ]


def save_cases(cases: list[Case], path: str | Path) -> None:
    def enc(c: Case) -> dict:
        row = asdict(c)
        row["category"] = c.category.value
        row["final_category"] = c.final_category.value if c.final_category else None
        row["ai_category"] = c.ai_category.value if c.ai_category else None
        row["resolved_category"] = c.resolved_category.value if c.resolved_category else None
        return row

    Path(path).write_text(json.dumps([enc(c) for c in cases], indent=2), encoding="utf-8")


def load_cases(path: str | Path) -> list[Case]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for r in rows:
        r["category"] = Category(r["category"])
        r["final_category"] = Category(r["final_category"]) if r["final_category"] else None
        for key in ("ai_category", "resolved_category"):
            if r.get(key):
                r[key] = Category(r[key])
        out.append(Case(**r))
    return out
