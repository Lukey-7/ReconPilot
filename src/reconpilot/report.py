"""End-of-day exception report as an Excel workbook."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from reconpilot.impact import sort_by_impact
from reconpilot.ledger import BUCKETS, current_category
from reconpilot.mi import build_mi
from reconpilot.matching import ReconResult
from reconpilot.models import Case, DayData
from reconpilot.nav import Check, NavResult

_HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_STATUS_FILL = {
    "PASS": PatternFill("solid", fgColor="D9EAD3"),
    "WARN": PatternFill("solid", fgColor="FFF2CC"),
    "FAIL": PatternFill("solid", fgColor="F4CCCC"),
}
_MONEY = "#,##0.00;[Red]-#,##0.00"


def _table(ws, header: list[str], rows: list[list], widths: list[int], money_cols=(), wrap_cols=()) -> None:
    ws.append(header)
    for cell in ws[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        ws.append(row)
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if cell.column in money_cols:
                cell.number_format = _MONEY
            if cell.column in wrap_cols:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            else:
                cell.alignment = Alignment(vertical="top")
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions


def write_report(
    path: str | Path,
    day: DayData,
    recon: ReconResult,
    cases: list[Case],
    nav: NavResult,
    checks: list[Check],
    signed_off_by: str = "",
    ledger: list[Case] | None = None,
    history: dict[str, list[Case]] | None = None,
) -> Path:
    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"Daily reconciliation, {day.as_of}"
    ws["A1"].font = Font(bold=True, size=14)
    match_kinds = Counter(m.kind for m in recon.matches)
    break_kinds = Counter(b.kind.value for b in recon.breaks)
    statuses = Counter(c.status for c in cases)
    categories = Counter((c.final_category or c.category).value for c in cases)
    lines: list[tuple[str, object]] = [
        ("Book trades settling", sum(1 for t in day.book_trades if t.settle_date == day.as_of)),
        ("Custodian cash lines", len(day.custodian_cash)),
        ("Cash matches", len(recon.matches)),
        *[(f"  {k}", v) for k, v in sorted(match_kinds.items())],
        ("Breaks", len(recon.breaks)),
        *[(f"  {k}", v) for k, v in sorted(break_kinds.items())],
        ("Cases", len(cases)),
        *[(f"  {k}", v) for k, v in sorted(categories.items())],
        ("AI second opinions", sum(1 for c in cases if c.ai_status == "ACCEPTED")),
        ("  AI disagrees: needs review", sum(1 for c in cases if c.ai_flag)),
        ("  AI fell back to rules", sum(1 for c in cases if c.ai_status == "FALLBACK")),
        ("Material cases", sum(1 for c in cases if c.material)),
        ("Escalated cases", sum(1 for c in cases if c.escalated)),
        ("SLA breaches (open)", sum(1 for c in cases if c.sla_breached)),
        ("Cleared automatically today", sum(1 for c in (ledger or []) if c.cleared_on == str(day.as_of))),
        *[(f"  Open aged {b} days", sum(1 for c in cases if c.age_bucket == b)) for b in ("0-1", "2-5", ">5")],
        ("Net NAV impact of open cases", round(sum(c.nav_impact for c in cases if not c.cleared_on), 2)),
        ("Review status",", ".join(f"{k} {v}" for k, v in sorted(statuses.items())) or "none"),
        ("NAV", nav.nav),
        ("NAV per share", nav.nav_per_share),
        ("Movement vs prior", f"{nav.movement:+.2%}"),
        ("Checks failed", sum(1 for c in checks if c.status == "FAIL")),
        ("Checks with warnings", sum(1 for c in checks if c.status == "WARN")),
        ("Signed off by", signed_off_by or "not signed off"),
    ]
    for i, (label, value) in enumerate(lines, start=3):
        ws.cell(row=i, column=1, value=label)
        cell = ws.cell(row=i, column=2, value=value)
        if label in ("NAV",):
            cell.number_format = _MONEY
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 28

    names = {sid: s.name for sid, s in day.securities.items()}
    cases = sort_by_impact(cases)
    _table(
        wb.create_sheet("Exceptions"),
        ["Case", "Security", "Name", "NAV impact", "Impact (bp)", "Material", "Gross exposure",
         "First seen", "Age (days)", "Age bucket", "Escalated", "Escalation reason", "SLA (days)", "SLA breached",
         "Suggested cause", "Confidence", "Status", "Final cause",
         "Reviewed by", "Review note", "Explanation", "Draft query", "Breaks",
         "AI cause", "AI confidence", "AI flag", "AI explanation", "AI investigation steps",
         "AI draft query", "AI model", "AI status"],
        [[c.case_id, c.security_id, names.get(c.security_id, ""), c.nav_impact, c.nav_impact_bp,
          "YES" if c.material else "", c.gross_exposure,
          c.first_seen, c.age_days, c.age_bucket, "YES" if c.escalated else "", c.escalation_reason,
          c.sla_days, "YES" if c.sla_breached else "",
          c.category.value, c.confidence, c.status,
          c.final_category.value if c.final_category else "", c.reviewed_by, c.review_note, c.explanation,
          c.query_draft, ", ".join(c.break_ids),
          c.ai_category.value if c.ai_category else "", c.ai_confidence, c.ai_flag, c.ai_explanation,
          "\n".join(f"{i}. {s}" for i, s in enumerate(c.ai_steps, start=1)), c.ai_query, c.ai_model,
          c.ai_status + (f": {c.ai_fallback_reason}" if c.ai_fallback_reason else "")] for c in cases],
        [18, 15, 22, 16, 11, 9, 16, 12, 10, 10, 10, 30, 10, 12,
         18, 11, 14, 16, 14, 24, 70, 70, 16, 18, 11, 24, 70, 60, 70, 18, 30],
        money_cols=(4, 7),
        wrap_cols=(21, 22, 27, 28, 29, 31),
    )
    _table(
        wb.create_sheet("Breaks"),
        ["Break", "Kind", "Security", "Book", "Custodian", "Difference", "Reference", "Note"],
        [[b.break_id, b.kind.value, b.security_id, b.book_value, b.custodian_value, b.difference,
          b.reference, b.note] for b in recon.breaks],
        [9, 28, 15, 18, 18, 18, 16, 30],
        money_cols=(4, 5, 6),
    )
    _table(
        wb.create_sheet("Cash matching"),
        ["Match type", "Book references", "Custodian entry", "Book amount", "Custodian amount", "Difference"],
        [[m.kind, ", ".join(m.book_refs), m.custodian_entry, m.book_amount, m.custodian_amount, m.difference]
         for m in recon.matches],
        [14, 40, 16, 18, 18, 12],
        money_cols=(4, 5, 6),
    )
    checks_ws = wb.create_sheet("NAV checks")
    _table(checks_ws, ["Check", "Status", "Detail"], [[c.name, c.status, c.detail] for c in checks],
           [18, 10, 110], wrap_cols=(3,))
    for row in checks_ws.iter_rows(min_row=2):
        fill = _STATUS_FILL.get(row[1].value)
        if fill:
            row[1].fill = fill

    _mi_sheet(wb.create_sheet("MI"), build_mi(day.as_of, ledger if ledger is not None else cases, history), names)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def _block(ws, row: int, title: str, header: list[str], rows: list[list], money_cols=()) -> int:
    """Write a titled table starting at ``row``; return the next free row."""
    ws.cell(row=row, column=1, value=title).font = Font(bold=True, size=12)
    row += 1
    for col, text in enumerate(header, start=1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
    for values in rows or [["none"]]:
        row += 1
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            if col in money_cols:
                cell.number_format = _MONEY
    return row + 2


def _mi_sheet(ws, mi, names: dict[str, str]) -> None:
    ws["A1"] = f"Management information, {mi.as_of}"
    ws["A1"].font = Font(bold=True, size=14)
    row = 3

    causes = mi.causes
    grid = [[cause, *[mi.by_cause_age.get((cause, b), 0) for b in BUCKETS],
             sum(mi.by_cause_age.get((cause, b), 0) for b in BUCKETS),
             round(sum(mi.impact_by_cause_age.get((cause, b), 0.0) for b in BUCKETS), 2)]
            for cause in causes]
    if grid:
        grid.append(["Total", *[sum(r[i] for r in grid) for i in range(1, 5)], round(sum(r[5] for r in grid), 2)])
    row = _block(ws, row, "Open breaks by cause and age (business days)",
                 ["Cause", *BUCKETS, "Total", "Net NAV impact"], grid, money_cols=(6,))

    resolve = [[cause, n, avg] for cause, (n, avg) in sorted(mi.resolve_by_cause.items())]
    if resolve:
        resolve.append(["All causes", sum(r[1] for r in resolve), mi.avg_days_to_resolve])
    row = _block(ws, row, "Time to resolve (cleared cases)",
                 ["Cause", "Cases cleared", "Average business days"], resolve)

    top = [[c.case_id, c.security_id, names.get(c.security_id, ""), current_category(c).value, c.nav_impact,
            c.nav_impact_bp, c.age_days, "YES" if c.material else "", c.status] for c in mi.top_cases]
    row = _block(ws, row, "Top 5 open cases by NAV impact",
                 ["Case", "Security", "Name", "Cause", "NAV impact", "Impact (bp)", "Age", "Material", "Status"],
                 top, money_cols=(5,))

    sla = [[c.case_id, c.security_id, current_category(c).value, c.age_days, c.sla_days,
            "YES" if c.material else "", c.cleared_on or "open"] for c in mi.sla_breaches]
    row = _block(ws, row, "SLA breaches",
                 ["Case", "Security", "Cause", "Age (days)", "SLA (days)", "Material", "Cleared on"], sla)

    trend = [[t.as_of, t.open_cases, t.new_cases, t.cleared_cases, t.material_open, t.escalated_open,
              t.sla_breaches_open, t.aged_over_5, t.open_nav_impact, t.avg_days_to_resolve] for t in mi.trend]
    _block(ws, row, f"Trend, last {len(mi.trend)} business day(s)",
           ["Date", "Open", "New", "Cleared", "Material", "Escalated", "SLA breached", "Aged >5",
            "Open net NAV impact", "Avg days to resolve"], trend, money_cols=(9,))
    for col, width in zip("ABCDEFGHIJ", (22, 15, 22, 18, 16, 12, 14, 12, 20, 20)):
        ws.column_dimensions[col].width = width
