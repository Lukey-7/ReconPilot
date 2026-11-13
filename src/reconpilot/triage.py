"""Group breaks into cases and suggest a likely cause for each.

Breaks that share a security are almost always one problem seen from several
angles (a missing trade shows up as a quantity difference and an unexplained
cash line), so they are grouped into a single case. Each case is then run
through a fixed set of rules, in order, and the first rule that fits wins.

Every suggestion carries a confidence, a plain-English explanation with the
actual figures, and a draft query to send to the custodian or trading desk.
Nothing is closed automatically: an analyst approves, rejects or reclassifies
every case (see ``review.py``).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from reconpilot.matching import ReconResult
from reconpilot.models import BASE_CURRENCY, Break, BreakKind, Case, Category, DayData

_DIVIDEND_WORDS = ("DIV", "DISTRIBUTION", "INCOME", "COUPON")
_SIGN_OFF = "Kind regards,\nFund Operations"


@dataclass
class Suggestion:
    category: Category
    confidence: float
    explanation: str
    query: str


def _m(x: float) -> str:
    return f"{x:,.2f}"


def _q(x: float) -> str:
    return f"{x:,.0f}"


def triage(day: DayData, recon: ReconResult) -> list[Case]:
    groups: OrderedDict[str, list[Break]] = OrderedDict()
    for brk in recon.breaks:
        groups.setdefault(brk.security_id, []).append(brk)

    cases = []
    for n, (sid, breaks) in enumerate(groups.items(), start=1):
        s = classify(day, recon, sid, breaks)
        cases.append(
            Case(
                case_id=f"EX-{day.as_of:%Y%m%d}-{n:03d}",
                security_id=sid,
                category=s.category,
                confidence=round(s.confidence, 2),
                explanation=s.explanation,
                query_draft=s.query,
                break_ids=[b.break_id for b in breaks],
            )
        )
    return cases


def classify(day: DayData, recon: ReconResult, sid: str, breaks: list[Break]) -> Suggestion:
    ctx = _Context(day, recon, sid, breaks)
    for rule in (_split, _timing, _missing_trade, _dividend, _fx, _price):
        s = rule(ctx)
        if s:
            return s
    return _unknown(ctx)


class _Context:
    def __init__(self, day: DayData, recon: ReconResult, sid: str, breaks: list[Break]):
        self.day = day
        self.sid = sid
        self.breaks = breaks
        self.sec = day.securities.get(sid)
        self.name = f"{self.sec.name} ({sid})" if self.sec else sid or "an unidentified security"
        self.ccy = self.sec.currency if self.sec else BASE_CURRENCY
        self.fx = day.fx_rates.get(self.ccy, 1.0)
        self.pos = day.book_positions.get(sid)
        self.hold = day.custodian_holdings.get(sid)
        self.pending = {line.reference: line for line in recon.pending if line.reference}
        self.trades = {t.trade_id: t for t in day.book_trades}

        def of(kind):
            return [b for b in breaks if b.kind is kind]

        qty = of(BreakKind.QUANTITY)
        price = of(BreakKind.PRICE)
        self.qty = qty[0] if qty else None
        self.price = price[0] if price else None
        self.amount = of(BreakKind.CASH_AMOUNT)
        self.missing_at_cust = of(BreakKind.CASH_MISSING_AT_CUSTODIAN)
        self.missing_in_book = of(BreakKind.CASH_MISSING_IN_BOOK)

    @property
    def unit_price(self) -> float:
        if self.pos and self.pos.price > 0:
            return self.pos.price
        return self.hold.price if self.hold else 0.0

    def letter(self, subject: str, body: str) -> str:
        return f"Subject: {subject}\n\nHello,\n\n{body}\n\n{_SIGN_OFF}"


def _split(c: _Context) -> Suggestion | None:
    if not (c.qty and c.price and c.qty.book_value and c.qty.custodian_value and c.price.custodian_value):
        return None
    ratio = c.qty.custodian_value / c.qty.book_value
    price_ratio = c.price.book_value / c.price.custodian_value
    forward = ratio >= 1.5 and abs(ratio - round(ratio)) < 0.001
    reverse = 0 < ratio < 0.67 and abs(1 / ratio - round(1 / ratio)) < 0.001
    if not (forward or reverse) or abs(price_ratio / ratio - 1) > 0.005:
        return None
    label = f"{round(ratio)}-for-1 split" if forward else f"1-for-{round(1 / ratio)} reverse split"
    value_book = c.qty.book_value * c.price.book_value
    value_cust = c.qty.custodian_value * c.price.custodian_value
    explanation = (
        f"The custodian holds {_q(c.qty.custodian_value)} units of {c.name} against "
        f"{_q(c.qty.book_value)} in the book, and prices them at {c.price.custodian_value:,.4f} "
        f"against {c.price.book_value:,.4f}. Quantity and price have moved by the same factor in "
        f"opposite directions and the market value barely changes ({_m(value_book)} vs "
        f"{_m(value_cust)} {c.ccy}), which points to a {label} the custodian has processed "
        f"and the book has not."
    )
    query = c.letter(
        f"Corporate action confirmation for {c.sid}",
        f"Your statement for {c.day.as_of} reflects what looks like a {label} on {c.name}. "
        f"Could you confirm the event, the ratio, the ex-date and the source of the "
        f"announcement so we can update our records?",
    )
    return Suggestion(Category.STOCK_SPLIT, 0.95, explanation, query)


def _timing(c: _Context) -> Suggestion | None:
    if not c.missing_at_cust or c.missing_in_book or c.amount:
        return None
    if not all(b.reference in c.pending for b in c.missing_at_cust):
        return None
    refs = [b.reference for b in c.missing_at_cust]
    expected_gap = sum(c.trades[r].signed_quantity for r in refs if r in c.trades)
    consistent = c.qty is not None and abs((c.qty.book_value - c.qty.custodian_value) - expected_gap) < 1e-6
    later = sorted({c.pending[r].value_date for r in refs})
    explanation = (
        f"Trade {', '.join(refs)} in {c.name} was due to settle on {c.day.as_of} but the custodian "
        f"shows it as pending with value date {', '.join(map(str, later))}."
    )
    if c.qty:
        explanation += (
            f" The position difference of {_q(c.qty.book_value - c.qty.custodian_value)} units "
            + ("matches the trade exactly." if consistent else "does not fully match the trade, so check for a second issue.")
        )
    query = c.letter(
        f"Late settlement of {', '.join(refs)}",
        f"Trade {', '.join(refs)} in {c.name} was due to settle on {c.day.as_of} and is showing "
        f"as pending on your statement. Could you confirm the reason for the delay (failed "
        f"delivery, missing instruction or counterparty issue) and the expected settlement date?",
    )
    return Suggestion(Category.TIMING, 0.9 if consistent else 0.7, explanation, query)


def _missing_trade(c: _Context) -> Suggestion | None:
    if not c.qty:
        return None
    gap = c.qty.custodian_value - c.qty.book_value
    if c.missing_in_book:
        cash = sum(b.custodian_value for b in c.missing_in_book)
        implied = abs(gap) * c.unit_price * c.fx
        close = implied > 0 and abs(abs(cash) / implied - 1) < 0.03
        refs = ", ".join(b.reference for b in c.missing_in_book)
        explanation = (
            f"The custodian holds {_q(gap)} more units of {c.name} than the book and has settled "
            f"cash entry {refs} for {_m(cash)}. "
            + (
                f"That amount is consistent with {_q(abs(gap))} units at about "
                f"{c.unit_price:,.2f} {c.ccy}, so a trade appears to be missing from the book."
                if close
                else "The cash does not line up neatly with the quantity, so treat the cause as provisional."
            )
        )
        query = c.letter(
            f"Unrecognised settlement on {c.sid}",
            f"Your statement for {c.day.as_of} shows {_q(c.qty.custodian_value)} units of {c.name} "
            f"against {_q(c.qty.book_value)} in our records, together with cash entry {refs} for "
            f"{_m(cash)}. We hold no matching instruction. Could you send the trade details "
            f"(trade date, broker and instructing party) so we can confirm whether it belongs to the fund?",
        )
        return Suggestion(Category.MISSING_TRADE, 0.9 if close else 0.6, explanation, query)
    if c.missing_at_cust:
        refs = ", ".join(b.reference for b in c.missing_at_cust)
        explanation = (
            f"The book expects trade {refs} in {c.name} to have settled today, but the custodian "
            f"has neither the position change ({_q(-gap)} units) nor the cash, and shows nothing "
            f"pending. The custodian may not have received the instruction."
        )
        query = c.letter(
            f"Missing settlement for {refs}",
            f"We expected trade {refs} in {c.name} to settle on {c.day.as_of}, but it does not "
            f"appear on your holdings or cash statements, settled or pending. Could you confirm "
            f"whether you have received the instruction?",
        )
        return Suggestion(Category.MISSING_TRADE, 0.7, explanation, query)
    explanation = (
        f"Quantity of {c.name} differs by {_q(gap)} units (book {_q(c.qty.book_value)}, custodian "
        f"{_q(c.qty.custodian_value)}) with no related cash today. Possible free-of-payment "
        f"transfer or an older unbooked trade."
    )
    query = c.letter(
        f"Position difference on {c.sid}",
        f"Our records show {_q(c.qty.book_value)} units of {c.name} and your statement shows "
        f"{_q(c.qty.custodian_value)}. Could you send the movement history for the last five "
        f"business days?",
    )
    return Suggestion(Category.MISSING_TRADE, 0.55, explanation, query)


def _dividend(c: _Context) -> Suggestion | None:
    if c.qty or c.amount or c.missing_at_cust or not c.missing_in_book:
        return None
    credits = [b for b in c.missing_in_book if (b.custodian_value or 0) > 0]
    if len(credits) != len(c.missing_in_book):
        return None
    held = (c.hold.quantity if c.hold else 0.0) or (c.pos.quantity if c.pos else 0.0)
    if held <= 0:
        return None
    total = sum(b.custodian_value for b in credits)
    per_share = total / (held * c.fx)
    if not 0.0001 < per_share < 50 * (150 if c.ccy == "JPY" else 1):
        return None
    keyword = any(w in b.note.upper() for b in credits for w in _DIVIDEND_WORDS)
    explanation = (
        f"The custodian credited {_m(total)} against {c.name} with no matching entry in the book. "
        f"Spread over the {_q(held)} units held, that is {per_share:,.4f} {c.ccy} per share, "
        f"which looks like an income payment"
        + (" and the narrative says as much." if keyword else ", although the narrative does not say so.")
        + " The dividend has probably not been accrued."
    )
    query = c.letter(
        f"Income received on {c.sid}",
        f"We see a credit of {_m(total)} on {c.day.as_of} against {c.name}. Could you confirm "
        f"the event type, the rate per share, the ex-date and any withholding tax applied?",
    )
    return Suggestion(Category.DIVIDEND, 0.9 if keyword else 0.6, explanation, query)


def _fx(c: _Context) -> Suggestion | None:
    if c.qty or not c.amount:
        return None
    brk = c.amount[0]
    trade = c.trades.get(brk.reference)
    book, cust = brk.book_value, brk.custodian_value
    if c.ccy == BASE_CURRENCY or trade is None:
        return None
    book_gross = abs(book + trade.fees)
    cust_gross = abs(cust + trade.fees)
    rel = cust_gross / book_gross - 1
    if not 0.0005 <= abs(rel) <= 0.05:
        return None
    implied = trade.fx_rate * (1 + rel)
    explanation = (
        f"Trade {trade.trade_id} in {c.name} settled for {_m(cust)} against {_m(book)} expected, a "
        f"difference of {_m(cust - book)}. Quantity and price agree, and the gap is {rel:+.2%} of "
        f"the gross amount. Backing out the rate gives about {implied:.6f} USD per {c.ccy} against "
        f"{trade.fx_rate:.6f} in the book, so the custodian appears to have converted at a different rate."
    )
    query = c.letter(
        f"FX rate applied to {trade.trade_id}",
        f"Trade {trade.trade_id} in {c.name} settled for {_m(cust)}; we expected {_m(book)} using "
        f"a {c.ccy}/USD rate of {trade.fx_rate:.6f}. Could you confirm the rate you applied, its "
        f"source and the time it was struck?",
    )
    return Suggestion(Category.FX_DIFFERENCE, 0.8, explanation, query)


def _price(c: _Context) -> Suggestion | None:
    if c.qty or not c.price:
        return None
    book, cust = c.price.book_value, c.price.custodian_value
    rel = (cust - book) / book
    big = abs(rel) > 0.25
    explanation = (
        f"Quantities agree on {c.name}, but the custodian prices it at {cust:,.4f} {c.ccy} against "
        f"{book:,.4f} in the book ({rel:+.2%}), which moves the market value by "
        f"{_m((cust - book) * (c.pos.quantity if c.pos else 0) * c.fx)} USD."
        + (" A move this large may be a corporate action rather than a pricing difference." if big else "")
    )
    query = c.letter(
        f"Price check on {c.sid}",
        f"Your statement prices {c.name} at {cust:,.4f} {c.ccy} on {c.day.as_of}; our pricing "
        f"source gives {book:,.4f}. Could you confirm your price source and the time of the price?",
    )
    return Suggestion(Category.PRICE_MISMATCH, 0.5 if big else 0.85, explanation, query)


def _unknown(c: _Context) -> Suggestion:
    kinds = ", ".join(sorted({b.kind.value for b in c.breaks}))
    detail = ""
    if c.amount and c.ccy == BASE_CURRENCY:
        brk = c.amount[0]
        detail = (
            f" Trade {brk.reference} settled for {_m(brk.custodian_value)} against {_m(brk.book_value)} "
            f"in a base-currency security, so FX cannot explain it; check commission and fees."
        )
    explanation = f"Breaks on {c.name} ({kinds}) do not fit a known pattern.{detail} Needs manual investigation."
    query = c.letter(
        f"Reconciliation difference on {c.sid or 'cash'}",
        f"We have an unexplained difference on {c.name} for {c.day.as_of}. Could you send the "
        f"supporting detail for the entries involved?",
    )
    return Suggestion(Category.UNKNOWN, 0.3, explanation, query)
