"""Synthetic data for one fund-day, with known breaks planted on purpose.

The generator produces the three records an operations team compares every
morning (the fund's trades and positions, the custodian's holdings statement
and the custodian's cash statement) and then corrupts them in controlled ways.
Each corruption is recorded in an answer key so the pipeline can be scored.

Normal days are not perfectly clean either: the custodian rounds some amounts,
nets several trades into a single cash line, and a few book prices are stale.
None of those should be reported as breaks.
"""

from __future__ import annotations

import itertools
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from reconpilot.models import (
    BASE_CURRENCY,
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

BASE_FX = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067}
_COUNTRY = {"USD": "US", "EUR": "DE", "GBP": "GB", "JPY": "JP"}
_CCY_WEIGHTS = [60, 20, 12, 8]
_NAME_A = [
    "Alder", "Birch", "Cobalt", "Dunmore", "Ember", "Fairhaven", "Granite", "Harbour",
    "Ironvale", "Juniper", "Kestrel", "Larch", "Meridian", "Northgate", "Oakridge",
    "Pembrook", "Quarry", "Redfern", "Silverton", "Thornbury",
]
_NAME_B = [
    "Holdings", "Industries", "Capital", "Energy", "Systems", "Logistics", "Pharma",
    "Materials", "Networks", "Foods",
]
_DIVIDEND_TEXT = ["CASH DIVIDEND", "DIV PAYMENT", "INCOME DISTRIBUTION"]
_DIVIDEND_TEXT_HARD = ["CREDIT", "MISC RECEIPT", "CASH DIVIDEND"]


_DAILY_VOL = {"EQUITY": 0.012, "BOND": 0.002}


def _bond_name(rng: random.Random, as_of: date) -> str:
    coupon = rng.choice([1.25, 2.0, 2.75, 3.5, 4.125, 4.75, 5.5])
    return f"{coupon:g}% {as_of.year + rng.randint(2, 15)}"


@dataclass
class GeneratorConfig:
    n_securities: int = 80
    n_trades: int = 40
    aggregation_rate: float = 0.5  # chance the custodian nets a security's trades into one line
    rounding_noise_rate: float = 0.3  # chance a custodian amount is off by a few cents
    stale_prices: int = 2
    opening_cash: float = 50_000_000.0
    shares_outstanding: float = 10_000_000.0
    difficulty: str = "standard"  # "standard" or "hard"
    bond_share: float = 0.15  # share of the universe that is bonds rather than equities


def _make_universe(rng: random.Random, n: int) -> dict[str, Security]:
    currencies = rng.choices(list(BASE_FX), weights=_CCY_WEIGHTS, k=n)
    securities: dict[str, Security] = {}
    for i, ccy in enumerate(currencies, start=1):
        sid = f"{_COUNTRY[ccy]}{i:06d}{rng.randrange(1000):03d}{i % 10}"
        name = f"{rng.choice(_NAME_A)} {rng.choice(_NAME_B)}"
        securities[sid] = Security(sid, name, ccy)
    return securities


def generate_day(
    as_of: date,
    plants: list[Category],
    seed: int = 0,
    config: GeneratorConfig | None = None,
) -> tuple[DayData, list[PlantedBreak]]:
    """Build one day of data and plant one break per entry in ``plants``.

    Each planted break gets a security of its own, so the answer key can be
    matched to exceptions by security identifier.
    """
    cfg = config or GeneratorConfig()
    hard = cfg.difficulty == "hard"
    rng = random.Random(seed)

    securities = _make_universe(rng, cfg.n_securities)
    fx = {
        ccy: 1.0 if ccy == BASE_CURRENCY else round(rate * (1 + rng.uniform(-0.01, 0.01)), 6)
        for ccy, rate in BASE_FX.items()
    }
    trade_date = as_of - timedelta(days=2)

    prior_qty = {sid: float(rng.randrange(10, 500) * 100) for sid in securities}
    price: dict[str, float] = {}
    for sid, sec in securities.items():
        p = rng.uniform(5, 400)
        if sec.currency == "JPY":
            p *= 150
        price[sid] = round(p, 2)

    # Asset classes and prior-day prices come from a separate random stream, so
    # the breaks planted for a given seed are unchanged by these additions.
    side = random.Random(f"{seed}-static")
    for sid, sec in list(securities.items()):
        if side.random() < cfg.bond_share:
            securities[sid] = Security(sid, sec.name.split()[0] + " " + _bond_name(side, as_of), sec.currency, "BOND")
            price[sid] = round(side.uniform(92, 108), 3)

    # Reserve a distinct security for each planted break.
    pool = list(securities)
    rng.shuffle(pool)
    assigned: list[tuple[Category, str]] = []
    for cat in plants:
        if cat is Category.FX_DIFFERENCE:
            sid = next((s for s in pool if securities[s].currency != BASE_CURRENCY), None)
        else:
            sid = pool[0] if pool else None
        if sid is None:
            raise ValueError("not enough securities in the universe for the requested breaks")
        pool.remove(sid)
        assigned.append((cat, sid))
    active = pool

    trade_no = itertools.count(1)

    def make_trade(sid: str, prefix: str = "T") -> Trade:
        side = rng.choice([Side.BUY, Side.SELL])
        qty = float(rng.randrange(1, 50) * 100)
        if side is Side.SELL:
            qty = min(qty, prior_qty[sid])
        px = round(price[sid] * (1 + rng.uniform(-0.01, 0.01)), 2)
        ccy = securities[sid].currency
        fees = round(qty * px * fx[ccy] * 0.0005, 2)
        trade_id = f"{prefix}{as_of:%y%m%d}{next(trade_no):04d}"
        return Trade(trade_id, trade_date, as_of, sid, side, qty, px, ccy, fx[ccy], fees)

    cash_lines: list[CashLine] = []
    entry_no = itertools.count(1)

    def add_cash(value_date: date, sid: str, ref: str, desc: str, amount: float) -> None:
        entry = f"CS{next(entry_no):06d}"
        cash_lines.append(CashLine(entry, value_date, sid, ref, desc, round(amount, 2)))

    def noise() -> float:
        if rng.random() < cfg.rounding_noise_rate:
            return round(rng.uniform(-0.4, 0.4), 2)
        return 0.0

    # Ordinary trading, concentrated on a subset of names so some have several trades.
    traded_names = active[: max(1, min(len(active), cfg.n_trades // 2))]
    book_trades = [make_trade(rng.choice(traded_names)) for _ in range(cfg.n_trades)]

    by_security: dict[str, list[Trade]] = defaultdict(list)
    for t in book_trades:
        by_security[t.security_id].append(t)
    for sid, trades in by_security.items():
        if len(trades) >= 2 and rng.random() < cfg.aggregation_rate:
            group, rest = trades[:4], trades[4:]
            total = sum(t.cash_amount for t in group) + noise()
            add_cash(as_of, sid, f"NET-{sid}", "NET SETTLEMENT", total)
        else:
            rest = trades
        for t in rest:
            ref = "" if hard and rng.random() < 0.1 else t.trade_id
            desc = f"{t.side.value} {t.quantity:.0f} {sid}"
            add_cash(as_of, sid, ref, desc, t.cash_amount + noise())

    book_qty = dict(prior_qty)
    for t in book_trades:
        book_qty[t.security_id] += t.signed_quantity
    cust_qty = dict(book_qty)
    cust_price = dict(price)
    price_date = {sid: as_of for sid in securities}
    for sid in rng.sample(active, min(cfg.stale_prices, len(active))):
        price_date[sid] = as_of - timedelta(days=4)

    truth: list[PlantedBreak] = []
    for cat, sid in assigned:
        ccy = securities[sid].currency
        if cat is Category.MISSING_TRADE:
            t = make_trade(sid, prefix="X")
            cust_qty[sid] += t.signed_quantity
            ref = f"CUS{rng.randrange(10**6):06d}"
            add_cash(as_of, sid, ref, f"{t.side.value} {t.quantity:.0f} {sid}", t.cash_amount)
            detail = f"custodian settled a {t.side.value} of {t.quantity:.0f} that the book does not hold"
        elif cat is Category.PRICE_MISMATCH:
            lo, hi = (0.001, 0.03) if hard else (0.01, 0.08)
            dev = rng.uniform(lo, hi) * rng.choice([-1, 1])
            cust_price[sid] = round(price[sid] * (1 + dev), 4)
            detail = f"custodian price off by {dev:+.2%}"
        elif cat is Category.STOCK_SPLIT:
            ratio = rng.choice([2, 3, 4, 5])
            cust_qty[sid] *= ratio
            cust_price[sid] = round(price[sid] / ratio, 6)
            detail = f"{ratio}-for-1 split applied by custodian only"
        elif cat is Category.DIVIDEND:
            dps = rng.uniform(0.05, 2.0) * (150 if ccy == "JPY" else 1)
            texts = _DIVIDEND_TEXT_HARD if hard else _DIVIDEND_TEXT
            ref = f"DV{rng.randrange(10**6):06d}"
            # Under hard difficulty some custodians post income without a security identifier.
            line_sid = "" if hard and rng.random() < 0.3 else sid
            add_cash(as_of, line_sid, ref, f"{rng.choice(texts)} {line_sid}".strip(), book_qty[sid] * dps * fx[ccy])
            detail = f"dividend of {dps:.4f} per share not accrued in book"
        elif cat is Category.FX_DIFFERENCE:
            t = make_trade(sid)
            book_trades.append(t)
            book_qty[sid] += t.signed_quantity
            cust_qty[sid] += t.signed_quantity
            lo, hi = (0.0001, 0.006) if hard else (0.005, 0.025)
            dev = rng.uniform(lo, hi) * rng.choice([-1, 1])
            notional = round(t.quantity * t.price * fx[ccy] * (1 + dev), 2)
            amount = (-notional if t.side is Side.BUY else notional) - t.fees
            add_cash(as_of, sid, t.trade_id, f"{t.side.value} {t.quantity:.0f} {sid}", amount)
            detail = f"custodian converted {ccy} at a rate {dev:+.2%} away from the book"
        elif cat is Category.TIMING:
            t = make_trade(sid)
            book_trades.append(t)
            book_qty[sid] += t.signed_quantity
            if not (hard and rng.random() < 0.3):
                add_cash(as_of + timedelta(days=1), sid, t.trade_id, "PENDING SETTLEMENT", t.cash_amount)
            detail = "trade settles a day late at the custodian"
        else:  # pragma: no cover - UNKNOWN is never planted
            raise ValueError(f"cannot plant {cat}")
        truth.append(PlantedBreak(cat, sid, detail))

    positions = {
        sid: Position(sid, book_qty[sid], price[sid], price_date[sid], securities[sid].currency)
        for sid in securities
    }
    holdings = {
        sid: Holding(sid, cust_qty[sid], cust_price[sid], securities[sid].currency)
        for sid in securities
    }

    prior_prices = {
        sid: round(price[sid] / (1 + side.gauss(0, _DAILY_VOL[securities[sid].asset_class])), 4)
        for sid in securities
    }

    day = DayData(
        as_of=as_of,
        securities=securities,
        fx_rates=fx,
        book_trades=book_trades,
        book_positions=positions,
        custodian_holdings=holdings,
        custodian_cash=cash_lines,
        book_opening_cash=cfg.opening_cash,
        custodian_opening_cash=cfg.opening_cash,
        prior_nav_per_share=0.0,
        shares_outstanding=cfg.shares_outstanding,
        accrued_expenses=0.0,
        prior_prices=prior_prices,
    )
    gross = sum(p.quantity * p.price * fx[p.currency] for p in positions.values())
    day.accrued_expenses = round(gross * 0.0002, 2)
    nav_ps = (gross + day.book_closing_cash - day.accrued_expenses) / cfg.shares_outstanding
    day.prior_nav_per_share = round(nav_ps * (1 + rng.uniform(-0.008, 0.008)), 6)
    return day, truth
