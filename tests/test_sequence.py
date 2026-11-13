"""Multi-day data, the multi-day evaluation and multi-day CLI runs."""

import csv
import json
from datetime import date

from reconpilot.cli import main
from reconpilot.evaluate import run_sequence_evaluation, sequence_markdown
from reconpilot.matching import carry_forward
from reconpilot.models import Category
from reconpilot.pipeline import run_day
from reconpilot.sequence import SequenceConfig, generate_sequence
from reconpilot.storage import load_cases, read_day, read_truth, write_day

START = date(2026, 11, 9)


def test_sequence_is_deterministic_and_breaks_persist_until_fixed():
    a = generate_sequence(START, 6, 4, seed=5)
    b = generate_sequence(START, 6, 4, seed=5)
    assert [t for _, t in a] == [t for _, t in b]
    assert [d.as_of for d, _ in a][-1] == date(2026, 11, 16)  # skips the weekend

    first_truth = a[0][1]
    for p in first_truth:
        visible = [d.as_of for d, truth in a if any(q.security_id == p.security_id and q.start == p.start
                                                    for q in truth)]
        expected = [d.as_of for d, _ in a if p.start <= d.as_of < p.fix]
        assert visible == expected


def test_balances_roll_forward():
    seq = generate_sequence(START, 3, 3, seed=1)
    for (prev, _), (day, _) in zip(seq, seq[1:]):
        # The book writes off the custodian's few-cent rounding when it rolls cash forward.
        assert abs(day.book_opening_cash - prev.book_closing_cash) < 10
        assert day.custodian_opening_cash == prev.custodian_closing_cash
        assert day.accrued_expenses == round(prev.accrued_expenses + prev.accrued_today, 2)
        assert day.prior_prices == {sid: p.price for sid, p in prev.book_positions.items()}


def test_clean_sequence_raises_no_cases():
    seq = generate_sequence(START, 4, 0, seed=3, config=SequenceConfig(missed_accrual_rate=0))
    prev, prior = None, []
    for day, truth in seq:
        assert truth == []
        if prev is not None:
            day.carried_book_items, day.carried_custodian_lines = carry_forward(prev.recon)
        prev = run_day(day, prior)
        prior = prev.open_cases
        assert prev.recon.breaks == []
        checks = {c.name: c.status for c in prev.checks}
        assert checks["Cash tie-out"] == "PASS"
        assert checks["Accruals"] == "PASS"


def test_multi_day_evaluation_standard():
    r = run_sequence_evaluation(days=8, breaks_per_day=6, seed=9)
    assert r.planted == 48
    assert r.detected_first_day == r.planted
    assert r.cleared_early == 0
    assert r.cleared_on_fix_day == r.due_to_clear > 0
    assert r.correct_at_resolution == r.resolved_matched
    assert r.false_alarm_cases == 0
    assert "Cleared automatically on the fix day" in sequence_markdown([r], "test")


def test_multi_day_evaluation_hard_resolves_late_settlements():
    r = run_sequence_evaluation(days=10, breaks_per_day=6, seed=9, difficulty="hard")
    timing = r.per_category[Category.TIMING]
    # Some late settlements look like missing trades on day one, but all resolve as TIMING.
    assert timing["correct_at_resolution"] == timing["cleared_on_fix_day"] > 0
    assert r.cleared_early == 0


def test_day_files_round_trip_with_book_cash_and_accruals(tmp_path):
    seq = generate_sequence(START, 3, 4, seed=2)
    day, truth = next((d, t) for d, t in seq if d.book_cash) if any(d.book_cash for d, _ in seq) else seq[-1]
    write_day(day, tmp_path, truth)
    back = read_day(tmp_path)
    assert back.book_cash == day.book_cash
    assert back.accruals == day.accruals
    assert back.management_fee_rate == day.management_fee_rate
    assert read_truth(tmp_path) == truth


def test_cli_multi_day_run(tmp_path, capsys):
    data, run = tmp_path / "data", tmp_path / "run"
    assert main(["generate", "--as-of", str(START), "--days", "4", "--breaks", "4", "--out", str(data)]) == 0
    folders = sorted(data.iterdir())
    assert [f.name for f in folders] == ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]

    for f in folders:
        assert main(["run", "--data", str(f), "--out", str(run), "--user", "priya"]) == 0
    state = json.loads((run / "run.json").read_text())
    assert state["as_of"] == "2026-11-12" and len(state["days"]) == 4

    actions = [json.loads(line)["action"] for line in (run / "audit.jsonl").read_text().splitlines()]
    assert "CASE_AUTO_CLEARED" in actions and "CASE_ESCALATED" in actions
    assert main(["verify-audit", "--run", str(run)]) == 0

    open_now = load_cases(run / "cases.json")
    assert any(c.first_seen < "2026-11-12" for c in open_now)  # carried over from earlier days
    rows = list(csv.DictReader((run / "mi.csv").open()))
    assert {r["as_of"] for r in rows} == {f.name for f in folders}

    # Re-running the last day replaces its snapshot instead of compounding it.
    assert main(["run", "--data", str(folders[-1]), "--out", str(run), "--user", "priya"]) == 0
    again = load_cases(run / "cases.json")
    assert sorted(c.case_id for c in again) == sorted(c.case_id for c in open_now)

    capsys.readouterr()
    assert main(["queue", "--run", str(run)]) == 0
    assert "largest NAV impact first" in capsys.readouterr().out
