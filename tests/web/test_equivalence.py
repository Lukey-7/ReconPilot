"""The same files through the command line and through the web pipeline give the same results (spec 7.6).

Five consecutive business days of hard data (seed 11, four new breaks a day) go
through ``reconpilot run``, ``review`` and ``signoff`` into a run folder, and
through the API (upload, run with the worker's handler, decide, sign off) into
PostgreSQL. Every day the two must agree on the open cases and the cases cleared
that day, the NAV, the checks, and the audit trail once the web-only entries
(sign-ins, uploads, validation, run bookkeeping, user and fund creation) are
taken out.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from reconpilot import cli as engine_cli
from reconpilot.ledger import load_ledger
from reconpilot.sequence import SequenceConfig, generate_sequence
from reconpilot.storage import case_from_dict, load_cases, write_day
from reconpilot_web import jobs
from reconpilot_web.auditlog import DbAuditLog, verify_chain
from reconpilot_web.models import BusinessDay, CaseSnapshot
from reconpilot_web.validation import FILE_KINDS

from .conftest import FUND_CODE, FUND_START
from .test_upload import upload

DAYS, BREAKS, SEED = 5, 4, 11
ANALYST, APPROVER, SIGNER = "priya", "ann", "tom"

# Actions only the web application writes: account, upload, validation and run bookkeeping.
WEB_ONLY_PREFIXES = ("SIGN_IN", "FILES_UPLOADED", "VALIDATION_", "RUN_", "USER_CREATED", "FUND_CREATED")

CASE_FIELDS = ("category", "status", "nav_impact", "age_days", "cleared_on", "resolved_category")


@pytest.fixture(scope="module")
def sequence_folders(tmp_path_factory) -> list[Path]:
    """The five days written by the engine's own ``write_day``, one folder each."""
    root = tmp_path_factory.mktemp("equivalence_data")
    seq = generate_sequence(FUND_START, DAYS, BREAKS, seed=SEED, config=SequenceConfig(difficulty="hard"))
    return [write_day(day, root / str(day.as_of), truth) for day, truth in seq]


def web_only(action: str) -> bool:
    return action.startswith(WEB_ONLY_PREFIXES)


def decisions_for(cases) -> tuple[list[str], list[str]]:
    """Who approves what: escalated cases without an approver's decision go to the approver,
    every other pending case to the analyst. Both lists in case-id order."""
    by_approver = sorted(c.case_id for c in cases
                         if not c.cleared_on and c.escalated and c.reviewed_role != "approver")
    by_analyst = sorted(c.case_id for c in cases
                        if not c.cleared_on and c.status == "PENDING" and c.case_id not in by_approver)
    return by_analyst, by_approver


def case_view(cases, as_of: date) -> dict[str, tuple]:
    """The compared fields of the cases open at the end of ``as_of`` or cleared on it."""
    out = {}
    for c in cases:
        if c.cleared_on and c.cleared_on != str(as_of):
            continue
        out[c.case_id] = (
            c.category.value, c.status, c.nav_impact, c.age_days, c.cleared_on or None,
            c.resolved_category.value if c.resolved_category else None,
        )
    return out


# --------------------------------------------------------------------------- the command line


def write_decisions(path: Path, case_ids: list[str]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "decision", "category", "note"])
        for case_id in case_ids:
            writer.writerow([case_id, "approve", "", ""])
    return path


def cli_day(run: Path, folder: Path, as_of: date, scratch: Path) -> dict:
    """One day through ``reconpilot``: run, decide, sign off. Returns what the comparison needs."""
    assert engine_cli.main(["run", "--data", str(folder), "--out", str(run), "--user", ANALYST]) == 0
    after_run = case_view(load_ledger(run, as_of), as_of)

    by_analyst, by_approver = decisions_for(load_cases(run / "cases.json"))
    if by_analyst:
        csv_path = write_decisions(scratch / f"analyst_{as_of}.csv", by_analyst)
        assert engine_cli.main(["review", "--run", str(run), "--user", ANALYST, "--decisions", str(csv_path)]) == 0
    if by_approver:
        csv_path = write_decisions(scratch / f"approver_{as_of}.csv", by_approver)
        assert engine_cli.main(["review", "--run", str(run), "--user", APPROVER, "--role", "approver",
                                "--decisions", str(csv_path)]) == 0
    assert engine_cli.main(["signoff", "--run", str(run), "--user", SIGNER, "--role", "approver"]) == 0

    entries = [json.loads(line) for line in (run / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    raised = [e for e in entries if e["action"] == "CASES_RAISED"][-1]["payload"]
    return {
        "after_run": after_run,
        "after_signoff": case_view(load_ledger(run, as_of), as_of),
        "decisions": (by_analyst, by_approver),
        "nav_per_share": raised["nav_per_share"],
        "checks": raised["checks"],
        "cases_raised": raised,
    }


# --------------------------------------------------------------------------- the web application


def web_cases(db_session, fund_id: int, as_of: date):
    db_session.expire_all()
    rows = db_session.execute(
        select(CaseSnapshot.data).where(CaseSnapshot.fund_id == fund_id, CaseSnapshot.as_of == as_of)
    ).scalars().all()
    return [case_from_dict(data) for data in rows]


def approve(client, case_ids: list[str], queue: dict[str, dict]) -> None:
    for case_id in case_ids:
        response = client.post(f"/api/funds/{FUND_CODE}/cases/{case_id}/decision",
                               json={"decision": "approve", "version": queue[case_id]["version"]})
        assert response.status_code == 200, response.text
        queue[case_id]["version"] = response.json()["version"]


def web_day(clients: dict, factory, db_session, fund_id: int, folder: Path, as_of: date) -> dict:
    """One day through the API: upload, run (the worker's handler), decide, sign off."""
    analyst, approver, signer = clients[ANALYST], clients[APPROVER], clients[SIGNER]
    files = {kind: (folder / name).read_bytes() for kind, name in FILE_KINDS.items() if (folder / name).exists()}
    response = upload(analyst, files, as_of=as_of)
    assert response.status_code == 200 and response.json()["status"] == "validated", response.text
    response = analyst.post(f"/api/funds/{FUND_CODE}/days/{as_of}/run")
    assert response.status_code == 202, response.text
    assert jobs.work_one(factory, "equivalence-worker") == response.json()["job_id"]

    day = analyst.get(f"/api/funds/{FUND_CODE}/days/{as_of}").json()
    assert day["status"] == "ready", day
    after_run = case_view(web_cases(db_session, fund_id, as_of), as_of)

    listed = analyst.get(f"/api/funds/{FUND_CODE}/days/{as_of}/cases")
    assert listed.status_code == 200, listed.text
    queue = {c["case_id"]: c for c in listed.json()}
    assert set(queue) == {k for k, v in after_run.items() if v[4] is None}

    by_analyst, by_approver = decisions_for(web_cases(db_session, fund_id, as_of))
    approve(analyst, by_analyst, queue)
    approve(approver, by_approver, queue)
    response = signer.post(f"/api/funds/{FUND_CODE}/days/{as_of}/signoff")
    assert response.status_code == 200, response.text

    db_session.expire_all()
    row = db_session.execute(
        select(BusinessDay).where(BusinessDay.fund_id == fund_id, BusinessDay.as_of == as_of)
    ).scalar_one()
    entries = DbAuditLog(db_session).entries(fund_id)
    raised = [e for e in entries if e["action"] == "CASES_RAISED"][-1]["payload"]
    return {
        "after_run": after_run,
        "after_signoff": case_view(web_cases(db_session, fund_id, as_of), as_of),
        "decisions": (by_analyst, by_approver),
        "nav_per_share": row.nav_per_share,
        "checks": {c["name"]: c["status"] for c in row.checks},
        "cases_raised": raised,
        "api_nav_per_share": day["nav"]["nav_per_share"],
    }


# --------------------------------------------------------------------------- the test


def test_web_matches_cli_over_five_days(sequence_folders, make_user, make_fund, make_client, db_engine,
                                        db_session, tmp_path):
    make_user(ANALYST, "analyst", display_name="Priya Shah")
    make_user(APPROVER, "approver", display_name="Ann Lee")
    make_user(SIGNER, "approver", display_name="Tom Reed")
    fund = make_fund()
    clients = {name: make_client(name) for name in (ANALYST, APPROVER, SIGNER)}
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    run = tmp_path / "run"

    days = [date.fromisoformat(folder.name) for folder in sequence_folders]
    assert days[0] == FUND_START and len(days) == DAYS
    carried_any = cleared_any = escalated_any = False
    for folder, as_of in zip(sequence_folders, days):
        cli = cli_day(run, folder, as_of, tmp_path)
        web = web_day(clients, factory, db_session, fund.id, folder, as_of)

        for stage in ("after_run", "after_signoff"):
            assert sorted(web[stage]) == sorted(cli[stage]), f"{as_of} {stage}: different cases"
            for case_id, fields in cli[stage].items():
                assert dict(zip(CASE_FIELDS, web[stage][case_id])) == dict(zip(CASE_FIELDS, fields)), (
                    f"{as_of} {stage}: {case_id} differs")
        assert web["decisions"] == cli["decisions"], f"{as_of}: different cases needed a decision"
        assert web["nav_per_share"] == cli["nav_per_share"] == web["api_nav_per_share"], f"{as_of}: NAV differs"
        assert web["checks"] == cli["checks"], f"{as_of}: checks differ"
        assert web["cases_raised"] == cli["cases_raised"], f"{as_of}: run summary differs"

        carried_any |= any(v[3] > 0 and v[4] is None for v in cli["after_run"].values())
        cleared_any |= any(v[4] == str(as_of) for v in cli["after_run"].values())
        escalated_any |= bool(cli["decisions"][1])

    # The run must have exercised the multi-day workflow, or the comparison proves little.
    assert carried_any and cleared_any and escalated_any

    cli_log = [json.loads(line) for line in (run / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    web_log = DbAuditLog(db_session).entries(fund.id)
    cli_actions = [e["action"] for e in cli_log if not web_only(e["action"])]
    web_actions = [e["action"] for e in web_log if not web_only(e["action"])]
    assert web_actions == cli_actions
    # The engine's own entries carry the same people and the same content on both sides.
    assert [(e["actor"], e["role"], e["action"], e["payload"]) for e in web_log if not web_only(e["action"])] == [
        (e["actor"], e["role"], e["action"], e["payload"]) for e in cli_log if not web_only(e["action"])
    ]
    assert verify_chain(db_session) == (True, None)
