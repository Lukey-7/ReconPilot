from datetime import date

from openpyxl import load_workbook

from reconpilot.cli import main
from reconpilot.evaluate import run_evaluation
from reconpilot.generator import generate_day
from reconpilot.matching import reconcile
from reconpilot.models import PLANTABLE
from reconpilot.storage import load_cases, read_day, read_truth, write_day

AS_OF = date(2026, 11, 13)


def test_generator_is_deterministic():
    a, ta = generate_day(AS_OF, PLANTABLE, seed=3)
    b, tb = generate_day(AS_OF, PLANTABLE, seed=3)
    assert a.custodian_cash == b.custodian_cash
    assert ta == tb


def test_clean_generated_day_has_no_breaks():
    day, truth = generate_day(AS_OF, [], seed=11)
    assert truth == []
    assert reconcile(day).breaks == []


def test_files_round_trip(tmp_path):
    day, truth = generate_day(AS_OF, PLANTABLE, seed=5)
    write_day(day, tmp_path, truth)
    back = read_day(tmp_path)
    assert back.custodian_cash == day.custodian_cash
    assert back.book_positions == day.book_positions
    assert read_truth(tmp_path) == truth
    assert len(reconcile(back).breaks) == len(reconcile(day).breaks)


def test_evaluation_standard_data():
    r = run_evaluation(days=5, breaks_per_day=12, seed=1)
    assert r.planted == 60
    assert r.detection_rate == 1.0
    assert r.classification_accuracy >= 0.95
    assert r.false_alarms == 0


def test_evaluation_hard_data_is_harder_but_usable():
    r = run_evaluation(days=10, breaks_per_day=12, seed=1, difficulty="hard")
    assert 0.85 <= r.detection_rate < 1.0 or r.classification_accuracy < 1.0
    assert r.classification_accuracy >= 0.8


def test_cli_end_to_end(tmp_path, capsys):
    assert main(["demo", "--dir", str(tmp_path)]) == 0
    run = tmp_path / "run"
    cases = load_cases(run / "cases.json")
    assert len(cases) == 12

    escalated = [c for c in cases if c.escalated]
    assert escalated and all(c.material for c in escalated)  # material cases escalate on day one

    decisions = tmp_path / "decisions.csv"
    rows = ["case_id,decision,category,note"] + [f"{c.case_id},approve,," for c in cases]
    decisions.write_text("\n".join(rows) + "\n")
    assert main(["review", "--run", str(run), "--user", "priya", "--decisions", str(decisions)]) == 0
    # An analyst's approval is not enough for escalated cases.
    assert main(["signoff", "--run", str(run), "--user", "tom", "--role", "approver"]) == 1
    for c in escalated:
        assert main(["review", "--run", str(run), "--user", "ann", "--role", "approver",
                     "--case", c.case_id, "--approve"]) == 0
    assert main(["signoff", "--run", str(run), "--user", "ann", "--role", "approver"]) == 1  # four-eyes
    assert main(["signoff", "--run", str(run), "--user", "tom", "--role", "approver"]) == 0
    assert main(["verify-audit", "--run", str(run)]) == 0

    wb = load_workbook(run / "exceptions_2026-11-13.xlsx")
    assert wb.sheetnames == ["Summary", "Exceptions", "Breaks", "Cash matching", "NAV checks", "MI"]
    assert (run / "mi.csv").read_text().startswith("as_of,metric,cause,age_bucket,value")
    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows(min_row=3) if r[0].value}
    assert summary["Signed off by"] == "tom"
    assert wb["Exceptions"].max_row == 13
