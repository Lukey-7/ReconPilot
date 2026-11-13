import csv

from openpyxl import load_workbook

from reconpilot.mi import build_mi, mi_rows, write_mi_csv
from reconpilot.models import Case, Category


def case(cid, cat, impact, first, age, bucket, cleared="", sla=False, material=False, resolved=None):
    return Case(case_id=cid, security_id=f"S{cid}", category=cat, confidence=0.9, explanation="",
                query_draft="", nav_impact=impact, nav_impact_bp=impact / 1000, material=material,
                first_seen=first, age_days=age, age_bucket=bucket, cleared_on=cleared, sla_breached=sla,
                sla_days=2 if material else 5, resolved_category=resolved)


def sample_history():
    d1 = [case("1", Category.DIVIDEND, 500, "2026-11-12", 0, "0-1"),
          case("2", Category.PRICE_MISMATCH, -90_000, "2026-11-12", 0, "0-1", material=True)]
    d2 = [case("1", Category.DIVIDEND, 500, "2026-11-12", 1, "0-1"),
          case("2", Category.PRICE_MISMATCH, -90_000, "2026-11-12", 1, "0-1", material=True),
          case("3", Category.MISSING_TRADE, 20, "2026-11-13", 0, "0-1")]
    d3 = [case("1", Category.DIVIDEND, 500, "2026-11-12", 2, "2-5", cleared="2026-11-16",
               resolved=Category.DIVIDEND),
          case("2", Category.PRICE_MISMATCH, -90_000, "2026-11-12", 2, "2-5", sla=True, material=True),
          case("3", Category.MISSING_TRADE, 20, "2026-11-13", 1, "0-1", cleared="2026-11-16",
               resolved=Category.TIMING),
          case("4", Category.FX_DIFFERENCE, -7_000, "2026-11-16", 0, "0-1")]
    return {"2026-11-12": d1, "2026-11-13": d2, "2026-11-16": d3}


def test_build_mi():
    history = sample_history()
    mi = build_mi("2026-11-16", history["2026-11-16"], history)
    assert mi.by_cause_age == {("PRICE_MISMATCH", "2-5"): 1, ("FX_DIFFERENCE", "0-1"): 1}
    assert mi.avg_days_to_resolve == 1.5  # 2 days (dividend) and 1 day (late settlement)
    assert mi.resolve_by_cause == {"DIVIDEND": (1, 2.0), "TIMING": (1, 1.0)}
    assert [c.case_id for c in mi.top_cases] == ["2", "4"]
    assert [c.case_id for c in mi.sla_breaches] == ["2"]
    assert [(t.as_of, t.open_cases, t.new_cases, t.cleared_cases) for t in mi.trend] == [
        ("2026-11-12", 2, 2, 0), ("2026-11-13", 3, 1, 0), ("2026-11-16", 2, 1, 2)]
    assert mi.trend[-1].open_nav_impact == -97_000.0


def test_mi_csv_is_tidy(tmp_path):
    path = write_mi_csv(tmp_path / "mi.csv", sample_history())
    rows = list(csv.DictReader(path.open()))
    assert set(rows[0]) == {"as_of", "metric", "cause", "age_bucket", "value"}
    keyed = {(r["as_of"], r["metric"], r["cause"], r["age_bucket"]): r["value"] for r in rows}
    assert keyed[("2026-11-16", "open_cases", "ALL", "ALL")] == "2"
    assert keyed[("2026-11-16", "open_cases", "PRICE_MISMATCH", "2-5")] == "1"
    assert keyed[("2026-11-16", "cleared_cases", "TIMING", "0-1")] == "1"
    assert keyed[("2026-11-16", "avg_days_to_resolve", "ALL", "ALL")] == "1.5"
    assert len(rows) == len(mi_rows(sample_history()))


def test_report_has_mi_sheet(tmp_path):
    from datetime import date

    from conftest import make_day

    from reconpilot.matching import reconcile
    from reconpilot.nav import compute_nav
    from reconpilot.report import write_report

    history = sample_history()
    day = make_day({"A": "USD"}, {"A": (10, 10)})
    day.as_of = date(2026, 11, 16)
    path = write_report(tmp_path / "r.xlsx", day, reconcile(day), history["2026-11-16"], compute_nav(day), [],
                        ledger=history["2026-11-16"], history=history)
    ws = load_workbook(path)["MI"]
    values = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    for heading in ("Open breaks by cause and age (business days)", "Time to resolve (cleared cases)",
                    "Top 5 open cases by NAV impact", "SLA breaches", "Trend, last 3 business day(s)"):
        assert heading in values
