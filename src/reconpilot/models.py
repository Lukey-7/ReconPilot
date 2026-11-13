"""Core data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

BASE_CURRENCY = "USD"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class BreakKind(str, Enum):
    """What the matcher found wrong. One root cause can produce several breaks."""

    QUANTITY = "QUANTITY"
    PRICE = "PRICE"
    CASH_AMOUNT = "CASH_AMOUNT"
    CASH_MISSING_AT_CUSTODIAN = "CASH_MISSING_AT_CUSTODIAN"
    CASH_MISSING_IN_BOOK = "CASH_MISSING_IN_BOOK"


class Category(str, Enum):
    """Likely root cause of an exception."""

    MISSING_TRADE = "MISSING_TRADE"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    STOCK_SPLIT = "STOCK_SPLIT"
    DIVIDEND = "DIVIDEND"
    FX_DIFFERENCE = "FX_DIFFERENCE"
    TIMING = "TIMING"
    UNKNOWN = "UNKNOWN"


PLANTABLE: list[Category] = [c for c in Category if c is not Category.UNKNOWN]


@dataclass(frozen=True)
class Security:
    security_id: str
    name: str
    currency: str


@dataclass
class Trade:
    trade_id: str
    trade_date: date
    settle_date: date
    security_id: str
    side: Side
    quantity: float
    price: float
    currency: str
    fx_rate: float  # units of base currency per unit of trade currency
    fees: float  # base currency

    @property
    def signed_quantity(self) -> float:
        return self.quantity if self.side is Side.BUY else -self.quantity

    @property
    def notional_base(self) -> float:
        return round(self.quantity * self.price * self.fx_rate, 2)

    @property
    def cash_amount(self) -> float:
        """Settlement cash in base currency: negative for buys, positive for sells."""
        gross = -self.notional_base if self.side is Side.BUY else self.notional_base
        return round(gross - self.fees, 2)


@dataclass
class Position:
    """A holding in the fund's own books."""

    security_id: str
    quantity: float
    price: float
    price_date: date
    currency: str


@dataclass
class Holding:
    """A holding on the custodian's statement."""

    security_id: str
    quantity: float
    price: float
    currency: str


@dataclass
class CashLine:
    """One line of the custodian cash statement, in base currency."""

    entry_id: str
    value_date: date
    security_id: str
    reference: str
    description: str
    amount: float


@dataclass
class DayData:
    """Everything the pipeline needs for one fund on one business day."""

    as_of: date
    securities: dict[str, Security]
    fx_rates: dict[str, float]
    book_trades: list[Trade]
    book_positions: dict[str, Position]
    custodian_holdings: dict[str, Holding]
    custodian_cash: list[CashLine]
    book_opening_cash: float
    custodian_opening_cash: float
    prior_nav_per_share: float
    shares_outstanding: float
    accrued_expenses: float

    @property
    def book_closing_cash(self) -> float:
        settling = sum(t.cash_amount for t in self.book_trades if t.settle_date == self.as_of)
        return round(self.book_opening_cash + settling, 2)

    @property
    def custodian_closing_cash(self) -> float:
        settled = sum(line.amount for line in self.custodian_cash if line.value_date == self.as_of)
        return round(self.custodian_opening_cash + settled, 2)


@dataclass
class Break:
    break_id: str
    kind: BreakKind
    security_id: str
    book_value: float | None
    custodian_value: float | None
    reference: str = ""
    note: str = ""

    @property
    def difference(self) -> float:
        return round((self.custodian_value or 0.0) - (self.book_value or 0.0), 6)


@dataclass
class Case:
    """A group of related breaks with a suggested cause, awaiting analyst review."""

    case_id: str
    security_id: str
    category: Category
    confidence: float
    explanation: str
    query_draft: str
    break_ids: list[str] = field(default_factory=list)
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, RECLASSIFIED
    final_category: Category | None = None
    reviewed_by: str = ""
    review_note: str = ""
    # Second opinion from the language model (see ai.py). Empty unless --ai is used.
    ai_category: Category | None = None
    ai_confidence: float | None = None
    ai_explanation: str = ""
    ai_steps: list[str] = field(default_factory=list)
    ai_query: str = ""
    ai_model: str = ""
    ai_status: str = ""  # "", ACCEPTED or FALLBACK
    ai_flag: str = ""  # set when the model disagrees with the rules
    ai_fallback_reason: str = ""


@dataclass
class PlantedBreak:
    """Answer-key entry written by the generator, used only for evaluation."""

    category: Category
    security_id: str
    detail: str
