from datetime import date

from conftest import make_day

from reconpilot.generator import generate_day
from reconpilot.matching import Tolerances, reconcile
from reconpilot.models import PLANTABLE, BreakKind, Security
from reconpilot.nav import compute_nav, price_moves, run_checks
from reconpilot.storage import read_day, write_day


def with_classes(day, classes):
    day.securities = {sid: Security(sid, s.name, s.currency, classes.get(sid, "EQUITY"))
                      for sid, s in day.securities.items()}
    return day


def test_price_tolerance_depends_on_asset_class():
    # A 0.15% price difference: inside the equity tolerance (0.25%), outside the bond one (0.10%).
    day = make_day({"EQ": "USD", "BD": "USD"}, {"EQ": (100, 100), "BD": (100, 100)},
                   holdings={"EQ": (100, 100.15), "BD": (100, 100.15)})
    with_classes(day, {"BD": "BOND"})
    breaks = reconcile(day).breaks
    assert [(b.kind, b.security_id) for b in breaks] == [(BreakKind.PRICE, "BD")]


def test_tolerances_are_configurable_per_class():
    day = make_day({"EQ": "USD"}, {"EQ": (100, 100)}, holdings={"EQ": (100, 100.15)})
    tight = Tolerances(price_rel_by_class={"EQUITY": 0.001})
    assert len(reconcile(day, tight).breaks) == 1


def test_day_on_day_price_move_check():
    day = make_day({"EQ": "USD", "BD": "USD", "OK": "USD"},
                   {"EQ": (100, 112), "BD": (100, 103), "OK": (100, 100.5)})
    with_classes(day, {"BD": "BOND", "OK": "BOND"})
    day.prior_prices = {"EQ": 100.0, "BD": 100.0, "OK": 100.0}
    flagged = price_moves(day)
    assert [(sid, cls) for sid, cls, _, _ in flagged] == [("EQ", "EQUITY"), ("BD", "BOND")]
    checks = {c.name: c for c in run_checks(day, compute_nav(day), reconcile(day))}
    assert checks["Day-on-day price moves"].status == "WARN"
    assert "EQ (equity) +12.0%" in checks["Day-on-day price moves"].detail


def test_price_move_check_skips_without_prior_prices():
    day = make_day({"EQ": "USD"}, {"EQ": (100, 112)})
    checks = {c.name: c for c in run_checks(day, compute_nav(day), reconcile(day))}
    assert checks["Day-on-day price moves"].status == "PASS"
    assert "skipped" in checks["Day-on-day price moves"].detail


def test_generator_includes_bonds_and_prior_prices(tmp_path):
    day, _ = generate_day(date(2026, 11, 13), PLANTABLE, seed=4)
    bonds = [s for s in day.securities.values() if s.asset_class == "BOND"]
    assert 4 <= len(bonds) <= 25
    assert all(90 <= day.book_positions[b.security_id].price <= 110 for b in bonds)
    assert set(day.prior_prices) == set(day.securities)
    assert price_moves(day) == []  # ordinary days stay inside the limits

    write_day(day, tmp_path)
    back = read_day(tmp_path)
    assert back.securities == day.securities
    assert back.prior_prices == day.prior_prices
