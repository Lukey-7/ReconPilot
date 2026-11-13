"""A run of consecutive business days for one fund, with breaks that live and die.

Where ``generator.generate_day`` builds one self-contained day, this module
simulates a fund over several days so the multi-day workflow can be tested:
prices drift, cash balances roll forward, accrued liabilities build up, and
each planted break stays visible until a fix day, when the side that was wrong
catches up:

=================  ==========================================  ==================================
Break              First day                                   Fix day
=================  ==========================================  ==================================
MISSING_TRADE      custodian settles a trade the book lacks    book books it, with the custodian's
                                                               reference
TIMING             book settles, custodian shows it pending    custodian settles (1-2 days late)
                   (or, in hard mode, not at all)
PRICE_MISMATCH     custodian price off                         custodian price corrected
STOCK_SPLIT        custodian applies the split                 book applies the split
DIVIDEND           custodian credits income                    book books the income
FX_DIFFERENCE      custodian converts at a different rate      book posts an FX adjustment
=================  ==========================================  ==================================

Cash breaks persist because the matcher carries unmatched items forward
(``ledger.py``), exactly as in a live run directory. Each day's answer key
lists the breaks visible that day, with their start and fix dates.
"""

from __future__ import annotations

import itertools
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from reconpilot.generator import (
    _DAILY_VOL,
    _DIVIDEND_TEXT,
    _DIVIDEND_TEXT_HARD,
    BASE_FX,
    GeneratorConfig,
    _book_accruals,
    _bond_name,
    _make_universe,
)
from reconpilot.models import (
    BASE_CURRENCY,
    PLANTABLE,
    BookCashEntry,
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


@dataclass
class SequenceConfig(GeneratorConfig):
    max_life_days: int = 6  # a planted break is fixed 1 to this many business days after it appears
    timing_lags: tuple[int, ...] = (1, 1, 1, 2)  # business days a late settlement is late by
    missed_accrual_rate: float = 0.05


@dataclass
class _Break:
    category: Category
    sid: str
    start: date
    fix: date
    detail: str = ""
    data: dict = field(default_factory=dict)


def business_days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def generate_sequence(
    start: date,
    days: int,
    breaks_per_day: int,
    seed: int = 0,
    config: SequenceConfig | None = None,
) -> list[tuple[DayData, list[PlantedBreak]]]:
    """Simulate ``days`` business days, planting ``breaks_per_day`` new breaks each day."""
    cfg = config or SequenceConfig()
    hard = cfg.difficulty == "hard"
    rng = random.Random(seed)
    side = random.Random(f"{seed}-static")

    securities = _make_universe(rng, cfg.n_securities)
    price: dict[str, float] = {}
    for sid, sec in list(securities.items()):
        if side.random() < cfg.bond_share:
            securities[sid] = Security(sid, sec.name.split()[0] + " " + _bond_name(side, start), sec.currency, "BOND")
            price[sid] = side.uniform(92, 108)
        else:
            price[sid] = rng.uniform(5, 400) * (150 if sec.currency == "JPY" else 1)
    units_book = {sid: float(rng.randrange(10, 500) * 100) for sid in securities}
    units_cust = dict(units_book)
    split_book = {sid: 1 for sid in securities}
    split_cust = {sid: 1 for sid in securities}
    fx = {ccy: 1.0 if ccy == BASE_CURRENCY else rate for ccy, rate in BASE_FX.items()}

    dates = business_days(start, days)
    calendar = business_days(start, days + cfg.max_life_days + 5)
    schedule = [PLANTABLE[i % len(PLANTABLE)] for i in range(days * breaks_per_day)]
    rng.shuffle(schedule)

    live: list[_Break] = []
    reserved: set[str] = set()
    book_cash = cust_cash = cfg.opening_cash
    accrued = 0.0
    prev_prices: dict[str, float] = {}
    prev_nav_ps: float | None = None
    out: list[tuple[DayData, list[PlantedBreak]]] = []

    def later(d: date, n: int) -> date:
        return calendar[calendar.index(d) + n]

    def book_px(sid: str) -> float:
        return round(price[sid] / split_book[sid], 4)

    def cust_px(sid: str, d: date) -> float:
        px = price[sid] / split_cust[sid]
        for b in live:
            if b.sid == sid and b.category is Category.PRICE_MISMATCH and b.start <= d < b.fix:
                px *= 1 + b.data["dev"]
        return round(px, 4)

    for i, d in enumerate(dates):
        # Market moves.
        if i:
            for sid, sec in securities.items():
                price[sid] *= 1 + side.gauss(0, _DAILY_VOL[sec.asset_class])
            for ccy in fx:
                if ccy != BASE_CURRENCY:
                    fx[ccy] = round(fx[ccy] * (1 + side.gauss(0, 0.003)), 6)

        trade_no = itertools.count(1)
        entry_no = itertools.count(1)
        trades: list[Trade] = []
        cash_lines: list[CashLine] = []
        book_entries: list[BookCashEntry] = []

        def make_trade(sid: str, trade_id: str | None = None) -> Trade:
            sd = rng.choice([Side.BUY, Side.SELL])
            qty = float(rng.randrange(1, 50) * 100)
            held = units_book[sid] * split_book[sid]
            if sd is Side.SELL and held < 100:
                sd = Side.BUY
            if sd is Side.SELL:
                qty = min(qty, held)
            px = round(book_px(sid) * (1 + rng.uniform(-0.01, 0.01)), 2)
            ccy = securities[sid].currency
            fees = round(qty * px * fx[ccy] * 0.0005, 2)
            tid = trade_id or f"T{d:%y%m%d}{next(trade_no):04d}"
            return Trade(tid, d - timedelta(days=2), d, sid, sd, qty, px, ccy, fx[ccy], fees)

        def add_cash(value_date: date, sid: str, ref: str, desc: str, amount: float) -> None:
            cash_lines.append(CashLine(f"CS{d:%y%m%d}{next(entry_no):05d}", value_date, sid, ref, desc,
                                       round(amount, 2)))

        rounding: list[float] = []

        def noise() -> float:
            n = round(rng.uniform(-0.4, 0.4), 2) if rng.random() < cfg.rounding_noise_rate else 0.0
            rounding.append(n)
            return n

        def move(sid: str, signed: float, book: bool, cust: bool) -> None:
            if book:
                units_book[sid] += signed / split_book[sid]
            if cust:
                units_cust[sid] += signed / split_cust[sid]

        # 1. Fixes due today.
        for b in [b for b in live if b.fix == d]:
            if b.category is Category.MISSING_TRADE:
                t0: Trade = b.data["trade"]
                late = Trade(b.data["ref"], t0.trade_date, d, t0.security_id, t0.side, t0.quantity, t0.price,
                             t0.currency, t0.fx_rate, t0.fees)
                trades.append(late)
                move(b.sid, late.signed_quantity, book=True, cust=False)
            elif b.category is Category.TIMING:
                t0 = b.data["trade"]
                move(b.sid, t0.signed_quantity, book=False, cust=True)
                add_cash(d, b.sid, t0.trade_id, f"{t0.side.value} {t0.quantity:.0f} {b.sid}", t0.cash_amount)
            elif b.category is Category.STOCK_SPLIT:
                split_book[b.sid] *= b.data["ratio"]
            elif b.category is Category.DIVIDEND:
                book_entries.append(BookCashEntry(b.data["ref"], d, b.sid, "Dividend income", b.data["amount"]))
            elif b.category is Category.FX_DIFFERENCE:
                book_entries.append(BookCashEntry(f"ADJ-{b.data['trade'].trade_id}", d, b.sid,
                                                  "FX adjustment", b.data["adjustment"]))
        for b in [b for b in live if b.fix < d]:
            live.remove(b)
            reserved.discard(b.sid)

        # 2. New breaks.
        free = [s for s in securities if s not in reserved]
        rng.shuffle(free)
        for cat in schedule[i * breaks_per_day:(i + 1) * breaks_per_day]:
            if cat is Category.FX_DIFFERENCE:
                sid = next((s for s in free if securities[s].currency != BASE_CURRENCY), None)
            else:
                sid = free[0] if free else None
            if sid is None:
                continue
            free.remove(sid)
            reserved.add(sid)
            if cat is Category.TIMING:
                fix = later(d, rng.choice(cfg.timing_lags))
            else:
                fix = later(d, rng.randint(1, cfg.max_life_days))
            b = _Break(cat, sid, d, fix)
            ccy = securities[sid].currency
            if cat is Category.MISSING_TRADE:
                ref = f"CUS{rng.randrange(10**6):06d}"
                t = make_trade(sid, trade_id=f"X{d:%y%m%d}{next(trade_no):04d}")
                move(sid, t.signed_quantity, book=False, cust=True)
                add_cash(d, sid, ref, f"{t.side.value} {t.quantity:.0f} {sid}", t.cash_amount)
                b.data, b.detail = {"trade": t, "ref": ref}, f"custodian settled {t.side.value} {t.quantity:.0f}"
            elif cat is Category.TIMING:
                t = make_trade(sid)
                trades.append(t)
                move(sid, t.signed_quantity, book=True, cust=False)
                b.data = {"trade": t, "report_pending": not (hard and rng.random() < 0.3)}
                b.detail = f"settles {fix} instead of {d}"
            elif cat is Category.PRICE_MISMATCH:
                lo, hi = (0.001, 0.03) if hard else (0.01, 0.08)
                b.data = {"dev": rng.uniform(lo, hi) * rng.choice([-1, 1])}
                b.detail = f"custodian price off by {b.data['dev']:+.2%}"
            elif cat is Category.STOCK_SPLIT:
                ratio = rng.choice([2, 3, 4, 5])
                split_cust[sid] *= ratio
                b.data, b.detail = {"ratio": ratio}, f"{ratio}-for-1 split applied by custodian first"
            elif cat is Category.DIVIDEND:
                dps = rng.uniform(0.05, 2.0) * (150 if ccy == "JPY" else 1)
                amount = round(units_book[sid] * split_book[sid] * dps * fx[ccy], 2)
                ref = f"DV{rng.randrange(10**6):06d}"
                line_sid = "" if hard and rng.random() < 0.3 else sid
                texts = _DIVIDEND_TEXT_HARD if hard else _DIVIDEND_TEXT
                add_cash(d, line_sid, ref, f"{rng.choice(texts)} {line_sid}".strip(), amount)
                b.data, b.detail = {"ref": ref, "amount": amount}, f"income of {dps:.4f} per unit not booked"
            elif cat is Category.FX_DIFFERENCE:
                t = make_trade(sid)
                trades.append(t)
                move(sid, t.signed_quantity, book=True, cust=True)
                lo, hi = (0.0001, 0.006) if hard else (0.005, 0.025)
                dev = rng.uniform(lo, hi) * rng.choice([-1, 1])
                notional = round(t.quantity * t.price * t.fx_rate * (1 + dev), 2)
                amount = round((-notional if t.side is Side.BUY else notional) - t.fees, 2)
                add_cash(d, sid, t.trade_id, f"{t.side.value} {t.quantity:.0f} {sid}", amount)
                b.data = {"trade": t, "adjustment": round(amount - t.cash_amount, 2)}
                b.detail = f"custodian rate {dev:+.2%} away from the book"
            live.append(b)

        # Pending lines for late settlements still outstanding.
        for b in live:
            if b.category is Category.TIMING and b.start <= d < b.fix and b.data["report_pending"]:
                t0 = b.data["trade"]
                add_cash(b.fix, b.sid, t0.trade_id, "PENDING SETTLEMENT", t0.cash_amount)

        # 3. Ordinary trading on securities without a live break.
        traded = [s for s in securities if s not in reserved]
        rng.shuffle(traded)
        traded = traded[: max(1, cfg.n_trades // 2)]
        ordinary = [make_trade(rng.choice(traded)) for _ in range(cfg.n_trades)]
        for t in ordinary:
            move(t.security_id, t.signed_quantity, book=True, cust=True)
        trades.extend(ordinary)
        by_sec: dict[str, list[Trade]] = defaultdict(list)
        for t in ordinary:
            by_sec[t.security_id].append(t)
        for sid, group in by_sec.items():
            rest = group
            if len(group) >= 2 and rng.random() < cfg.aggregation_rate:
                netted, rest = group[:4], group[4:]
                add_cash(d, sid, f"NET-{sid}-{d:%y%m%d}", "NET SETTLEMENT",
                         sum(t.cash_amount for t in netted) + noise())
            for t in rest:
                ref = "" if hard and rng.random() < 0.1 else t.trade_id
                add_cash(d, sid, ref, f"{t.side.value} {t.quantity:.0f} {sid}", t.cash_amount + noise())

        # 4. Statements.
        stale = set(rng.sample(sorted(securities), cfg.stale_prices))
        positions = {
            sid: Position(sid, round(units_book[sid] * split_book[sid], 4), book_px(sid),
                          d - timedelta(days=4) if sid in stale else d, sec.currency)
            for sid, sec in securities.items()
        }
        holdings = {
            sid: Holding(sid, round(units_cust[sid] * split_cust[sid], 4), cust_px(sid, d), sec.currency)
            for sid, sec in securities.items()
        }
        day = DayData(
            as_of=d,
            securities=dict(securities),
            fx_rates=dict(fx),
            book_trades=trades,
            book_positions=positions,
            custodian_holdings=holdings,
            custodian_cash=cash_lines,
            book_opening_cash=round(book_cash, 2),
            custodian_opening_cash=round(cust_cash, 2),
            prior_nav_per_share=0.0,
            shares_outstanding=cfg.shares_outstanding,
            accrued_expenses=round(accrued, 2),
            book_cash=book_entries,
            prior_prices=dict(prev_prices) if prev_prices else {
                sid: round(p.price / (1 + side.gauss(0, _DAILY_VOL[securities[sid].asset_class])), 4)
                for sid, p in positions.items()
            },
        )
        gross = sum(p.quantity * p.price * fx[p.currency] for p in positions.values())
        if prev_nav_ps is None:
            nav_ps = (gross + day.book_closing_cash - day.accrued_expenses) / cfg.shares_outstanding
            prev_nav_ps = round(nav_ps * (1 + rng.uniform(-0.004, 0.004)), 6)
        day.prior_nav_per_share = prev_nav_ps
        _book_accruals(day, cfg, side)

        truth = [
            PlantedBreak(b.category, b.sid, b.detail, b.start, b.fix)
            for b in live
            if b.start <= d < b.fix
        ]
        out.append((day, truth))

        # Roll balances forward. The book writes off the custodian's few-cent rounding
        # differences (matched within tolerance today) so they do not pile up.
        book_cash = day.book_closing_cash + round(sum(rounding), 2)
        cust_cash = day.custodian_closing_cash
        accrued = day.accrued_expenses + day.accrued_today
        prev_prices = {sid: p.price for sid, p in positions.items()}
        nav = gross + book_cash - accrued
        prev_nav_ps = round(nav / cfg.shares_outstanding, 6)
    return out
