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


ASSET_CLASSES = ("EQUITY", "BOND")


@dataclass(frozen=True)
class Security:
    security_id: str
    name: str
    currency: str
    asset_class: str = "EQUITY"


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
class BookCashEntry:
    """A non-trade cash movement booked by the fund (income, adjustments)."""

    reference: str
    value_date: date
    security_id: str
    description: str
    amount: float


@dataclass
class Accrual:
    """An expense accrued in the book for one day (base currency, positive = liability)."""

    accrual_date: date
    kind: str  # MANAGEMENT_FEE or EXPENSES
    amount: float


@dataclass
class CarriedItem:
    """A book cash item left unmatched on an earlier day, matched again today."""

    reference: str
    security_id: str
    amount: float
    origin_date: date


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
    accrued_expenses: float  # accrued liabilities brought forward from the prior day
    book_cash: list[BookCashEntry] = field(default_factory=list)
    accruals: list[Accrual] = field(default_factory=list)  # booked today
    prior_prices: dict[str, float] = field(default_factory=dict)  # book prices on the prior day
    management_fee_rate: float = 0.0  # a year, on NAV
    daily_expense_budget: float = 0.0
    # Open items from earlier days, matched again today (see ledger.py).
    carried_book_items: list[CarriedItem] = field(default_factory=list)
    carried_custodian_lines: list[CashLine] = field(default_factory=list)

    @property
    def book_closing_cash(self) -> float:
        settling = sum(t.cash_amount for t in self.book_trades if t.settle_date == self.as_of)
        other = sum(e.amount for e in self.book_cash if e.value_date == self.as_of)
        return round(self.book_opening_cash + settling + other, 2)

    @property
    def accrued_today(self) -> float:
        return round(sum(a.amount for a in self.accruals if a.accrual_date == self.as_of), 2)

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
    # NAV impact (impact.py)
    nav_impact: float = 0.0  # base currency, effect on NAV if the custodian's view is right
    nav_impact_bp: float = 0.0
    gross_exposure: float = 0.0
    material: bool = False
    # Lifecycle across days (ledger.py)
    break_kinds: list[str] = field(default_factory=list)
    first_seen: str = ""  # ISO date
    age_days: int = 0  # business days open
    age_bucket: str = "0-1"
    escalated: bool = False
    escalation_reason: str = ""
    sla_days: int = 0
    sla_breached: bool = False
    cleared_on: str = ""  # ISO date, set when a later day's data matches
    clear_reason: str = ""
    resolved_category: Category | None = None
    reviewed_role: str = ""


@dataclass
class PlantedBreak:
    """Answer-key entry written by the generator, used only for evaluation."""

    category: Category
    security_id: str
    detail: str
    start: date | None = None  # multi-day runs: first day the break is visible
    fix: date | None = None  # multi-day runs: day the data agrees again
