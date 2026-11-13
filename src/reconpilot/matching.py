"""Deterministic matching of the book against the custodian.

Positions are compared security by security (quantity and price). Cash is
matched in passes, from strictest to loosest:

1. EXACT       same reference, same amount to the cent
2. TOLERANCE   same reference, amount within tolerance
3. ATTRIBUTE   custodian line has no reference; same security and amount
4. MANY_TO_ONE several book trades netted by the custodian into one line
5. anything still paired by reference has a real amount difference

Whatever is left over on either side becomes a break.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from reconpilot.models import Break, BreakKind, CashLine, DayData


@dataclass
class Tolerances:
    cash_abs: float = 1.00  # base currency
    cash_rel: float = 0.0001  # 1 basis point of the amount
    price_rel: float = 0.0025  # 25 basis points
    quantity_abs: float = 0.0
    max_group: int = 4  # largest netted group tried for many-to-one


@dataclass
class BookCashItem:
    reference: str
    security_id: str
    amount: float


@dataclass
class CashMatch:
    kind: str
    book_refs: list[str]
    custodian_entry: str
    book_amount: float
    custodian_amount: float

    @property
    def difference(self) -> float:
        return round(self.custodian_amount - self.book_amount, 2)


@dataclass
class ReconResult:
    matches: list[CashMatch] = field(default_factory=list)
    breaks: list[Break] = field(default_factory=list)
    pending: list[CashLine] = field(default_factory=list)  # custodian lines value-dated later

    def breaks_for(self, security_id: str) -> list[Break]:
        return [b for b in self.breaks if b.security_id == security_id]


class _BreakFactory:
    def __init__(self) -> None:
        self._n = itertools.count(1)

    def __call__(self, kind, security_id, book_value, custodian_value, reference="", note=""):
        return Break(f"B{next(self._n):04d}", kind, security_id, book_value, custodian_value, reference, note)


def reconcile(day: DayData, tol: Tolerances | None = None) -> ReconResult:
    tol = tol or Tolerances()
    new_break = _BreakFactory()
    result = ReconResult()
    result.breaks.extend(_reconcile_positions(day, tol, new_break))
    matches, cash_breaks, pending = _match_cash(day, tol, new_break)
    result.matches = matches
    result.breaks.extend(cash_breaks)
    result.pending = pending
    return result


def _reconcile_positions(day: DayData, tol: Tolerances, new_break) -> list[Break]:
    breaks = []
    for sid in sorted(set(day.book_positions) | set(day.custodian_holdings)):
        book = day.book_positions.get(sid)
        cust = day.custodian_holdings.get(sid)
        book_qty = book.quantity if book else 0.0
        cust_qty = cust.quantity if cust else 0.0
        if abs(book_qty - cust_qty) > tol.quantity_abs:
            breaks.append(new_break(BreakKind.QUANTITY, sid, book_qty, cust_qty))
        if book and cust and book.price > 0:
            if abs(cust.price - book.price) / book.price > tol.price_rel:
                breaks.append(new_break(BreakKind.PRICE, sid, book.price, cust.price))
    return breaks


def _within(a: float, b: float, tol: Tolerances) -> bool:
    limit = max(tol.cash_abs, tol.cash_rel * max(abs(a), abs(b)))
    return abs(a - b) <= limit + 1e-9


def _match_cash(day: DayData, tol: Tolerances, new_break):
    book_open = {
        t.trade_id: BookCashItem(t.trade_id, t.security_id, t.cash_amount)
        for t in day.book_trades
        if t.settle_date == day.as_of
    }
    settled = [line for line in day.custodian_cash if line.value_date == day.as_of]
    pending = [line for line in day.custodian_cash if line.value_date > day.as_of]
    cust_open = {line.entry_id: line for line in settled}
    matches: list[CashMatch] = []
    breaks: list[Break] = []

    def close(kind: str, items: list[BookCashItem], line: CashLine) -> None:
        total = round(sum(i.amount for i in items), 2)
        matches.append(CashMatch(kind, [i.reference for i in items], line.entry_id, total, line.amount))
        for i in items:
            del book_open[i.reference]
        del cust_open[line.entry_id]

    # Passes 1 and 2: by reference.
    for kind, same in (
        ("EXACT", lambda a, b: abs(a - b) < 0.005),
        ("TOLERANCE", lambda a, b: _within(a, b, tol)),
    ):
        for line in list(cust_open.values()):
            item = book_open.get(line.reference) if line.reference else None
            if item and same(item.amount, line.amount):
                close(kind, [item], line)

    # Pass 3: custodian line without a reference, matched on security and amount.
    for line in list(cust_open.values()):
        if line.reference:
            continue
        candidates = [
            i for i in book_open.values()
            if i.security_id == line.security_id and _within(i.amount, line.amount, tol)
        ]
        if candidates:
            best = min(candidates, key=lambda i: abs(i.amount - line.amount))
            close("ATTRIBUTE", [best], line)

    # Pass 4: many-to-one netting.
    for line in list(cust_open.values()):
        candidates = [i for i in book_open.values() if i.security_id == line.security_id]
        found = None
        for size in range(2, min(tol.max_group, len(candidates)) + 1):
            for combo in itertools.combinations(candidates, size):
                if _within(sum(i.amount for i in combo), line.amount, tol):
                    found = list(combo)
                    break
            if found:
                break
        if found:
            close("MANY_TO_ONE", found, line)

    # Pass 5: same reference, amount genuinely different.
    for line in list(cust_open.values()):
        item = book_open.get(line.reference) if line.reference else None
        if item:
            breaks.append(
                new_break(BreakKind.CASH_AMOUNT, line.security_id, item.amount, line.amount, line.reference)
            )
            del book_open[item.reference]
            del cust_open[line.entry_id]

    for item in book_open.values():
        breaks.append(
            new_break(BreakKind.CASH_MISSING_AT_CUSTODIAN, item.security_id, item.amount, None, item.reference)
        )
    for line in cust_open.values():
        breaks.append(
            new_break(
                BreakKind.CASH_MISSING_IN_BOOK, line.security_id, None, line.amount,
                line.reference or line.entry_id, line.description,
            )
        )
    return matches, breaks, pending
