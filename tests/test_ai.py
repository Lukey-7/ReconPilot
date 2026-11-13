"""AI layer tests. A fake client stands in for the model; the network is blocked."""

import json
from datetime import timedelta

import pytest
from conftest import AS_OF, cash, make_day, trade

from reconpilot import ai
from reconpilot.ai import (
    DISAGREEMENT_FLAG,
    AIError,
    ResponseCache,
    assist_cases,
    build_evidence,
    make_client,
    unsupported_figures,
    validate_response,
)
from reconpilot.audit import AuditLog
from reconpilot.cli import main
from reconpilot.evaluate import run_evaluation
from reconpilot.matching import reconcile
from reconpilot.models import Category
from reconpilot.storage import load_cases
from reconpilot.triage import triage


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(ai.urllib.request, "urlopen", refuse)
    for var in ai.KEY_ENV.values():
        monkeypatch.delenv(var, raising=False)


class FakeClient:
    provider = "fake"
    effort = "medium"

    def __init__(self, respond, model="fake-1"):
        self.respond = respond  # evidence dict -> response text, or raises
        self.model = model
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        evidence = json.loads(user.split("\n\n", 1)[1])
        return self.respond(evidence)


def reply(category="STOCK_SPLIT", explanation=None, steps=None, **extra):
    body = {
        "category": category,
        "confidence": 0.9,
        "explanation": explanation
        or "The custodian holds 3,000 units against 1,000 in the book, priced at 30 against 90.",
        "investigation_steps": steps or ["Check the corporate actions feed.", "Ask the custodian for the notice."],
        "custodian_query": "Subject: Split on A\n\nHello, please confirm the event.",
        **extra,
    }
    return json.dumps(body)


def split_day():
    day = make_day({"A": "USD"}, {"A": (1000, 90)}, holdings={"A": (3000, 30)})
    recon = reconcile(day)
    return day, recon, triage(day, recon)


def run_one(respond, tmp_path, cache=None):
    day, recon, cases = split_day()
    audit = AuditLog(tmp_path / "audit.jsonl")
    client = FakeClient(respond)
    assist_cases(day, recon, cases, client, audit=audit, cache=cache)
    return cases[0], audit, client


def rules_unchanged(case):
    assert case.category is Category.STOCK_SPLIT
    assert case.confidence == 0.95
    assert "3-for-1" in case.explanation


def test_valid_response_is_accepted_and_audited(tmp_path):
    case, audit, _ = run_one(lambda ev: reply(), tmp_path)
    assert case.ai_status == "ACCEPTED"
    assert case.ai_category is Category.STOCK_SPLIT
    assert case.ai_flag == ""
    assert len(case.ai_steps) == 2
    assert case.ai_query.startswith("Subject:")
    rules_unchanged(case)

    entry = audit.entries()[-1]
    assert entry["action"] == "AI_CALL"
    assert entry["payload"]["model"] == "fake-1"
    assert len(entry["payload"]["prompt_hash"]) == 64
    assert entry["payload"]["response"] == reply()
    assert entry["payload"]["fallback_used"] is False
    assert audit.verify() == (True, None)


def test_malformed_json_falls_back(tmp_path):
    case, audit, _ = run_one(lambda ev: "Sure! Here is my answer: {category: SPLIT", tmp_path)
    assert case.ai_status == "FALLBACK"
    assert case.ai_category is None
    assert "malformed JSON" in case.ai_fallback_reason
    rules_unchanged(case)
    assert audit.entries()[-1]["payload"]["fallback_used"] is True


def test_invented_figures_are_rejected(tmp_path):
    made_up = "The custodian holds 3,000 units, a gain of 12,345.67 USD on the position."
    case, audit, _ = run_one(lambda ev: reply(explanation=made_up), tmp_path)
    assert case.ai_status == "FALLBACK"
    assert "12,345.67" in case.ai_fallback_reason
    rules_unchanged(case)


def test_category_outside_enum_is_rejected(tmp_path):
    case, _, _ = run_one(lambda ev: reply(category="CORPORATE_ACTION"), tmp_path)
    assert case.ai_status == "FALLBACK"
    assert "not an allowed value" in case.ai_fallback_reason


def test_disagreement_keeps_both_and_flags(tmp_path):
    case, audit, _ = run_one(lambda ev: reply(category="PRICE_MISMATCH"), tmp_path)
    assert case.ai_status == "ACCEPTED"
    assert case.ai_category is Category.PRICE_MISMATCH
    assert case.ai_flag == DISAGREEMENT_FLAG
    rules_unchanged(case)
    assert audit.entries()[-1]["payload"]["disagrees"] is True


@pytest.mark.parametrize("error", [AIError("HTTP 500: overloaded"), TimeoutError("timed out"), RuntimeError("boom")])
def test_client_errors_fall_back(tmp_path, error):
    def fail(ev):
        raise error

    case, audit, _ = run_one(fail, tmp_path)
    assert case.ai_status == "FALLBACK"
    assert case.ai_fallback_reason
    rules_unchanged(case)
    assert audit.entries()[-1]["payload"]["response"] is None


def test_missing_key_means_rules_only(tmp_path):
    assert make_client() is None
    assert make_client("openai") is None
    day, recon, cases = split_day()
    audit = AuditLog(tmp_path / "audit.jsonl")
    assist_cases(day, recon, cases, None, audit=audit)
    assert cases[0].ai_status == ""
    rules_unchanged(cases[0])
    assert [e["action"] for e in audit.entries()] == ["AI_UNAVAILABLE"]


def test_make_client_picks_provider_from_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    client = make_client()
    assert client.provider == "google" and client.model == ai.DEFAULT_MODELS["google"]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert make_client().provider == "openai"
    assert make_client("google", "gemini-x", "low").model == "gemini-x"


def test_cache_avoids_repeat_calls(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    first, _, c1 = run_one(lambda ev: reply(), tmp_path, cache)
    second, audit, c2 = run_one(lambda ev: reply(category="UNKNOWN"), tmp_path, cache)
    assert c1.calls == 1 and c2.calls == 0
    assert second.ai_category is Category.STOCK_SPLIT  # served from cache
    assert audit.entries()[-1]["payload"]["cached"] is True


@pytest.mark.parametrize("bad", [
    json.dumps({"category": "DIVIDEND"}),
    reply(steps=["only one step"]),
    reply(steps=["a", "b", "c", "d", "e"]),
    reply(confidence_note="extra field"),
    json.dumps({**json.loads(reply()), "confidence": 1.7}),
    json.dumps({**json.loads(reply()), "confidence": "high"}),
    json.dumps({**json.loads(reply()), "explanation": ""}),
    "[1, 2, 3]",
])
def test_schema_violations(bad):
    with pytest.raises(AIError):
        validate_response(bad)


def test_fenced_json_is_accepted():
    assert validate_response("```json\n" + reply() + "\n```")["category"] == "STOCK_SPLIT"


def test_figure_check_allows_rounding_and_identifiers():
    evidence = {"a": 10_005.37, "b": 1.2345, "c": "rate 0.004912", "id": "US0000075627"}
    ok = "Entry CUS000123 on 2026-11-13 for 10,005.37 (about 10,005), off by 1.23% and 0.4912%, 3 lines."
    assert unsupported_figures(ok, evidence) == []
    assert unsupported_figures("A loss of 10,500.00 on 75627 shares.", evidence) == ["10,500.00", "75627"]


def test_evidence_includes_narrative_pending_lines_and_rule_suggestion():
    t = trade("T1", "A", qty=200, price=50)
    late = cash("C1", "A", "T1", t.cash_amount, "PENDING SETTLEMENT", value_date=AS_OF + timedelta(days=1))
    div = cash("C2", "B", "DV1", 450.0, "MISC RECEIPT")
    day = make_day({"A": "USD", "B": "USD"}, {"A": (1200, 50), "B": (1000, 50)}, [t],
                   holdings={"A": (1000, 50), "B": (1000, 50)}, cash_lines=[late, div])
    recon = reconcile(day)
    cases = {c.security_id: c for c in triage(day, recon)}
    ev_a = build_evidence(day, recon, cases["A"])
    assert ev_a["custodian_cash_pending"][0]["narrative"] == "PENDING SETTLEMENT"
    assert ev_a["book_trades"][0]["trade_id"] == "T1"
    assert ev_a["rule_based_suggestion"]["category"] == "TIMING"
    ev_b = build_evidence(day, recon, cases["B"])
    assert ev_b["breaks"][0]["custodian_narrative"] == "MISC RECEIPT"
    assert ev_b["derived"]["amount_per_unit_held_local_ccy"] == 0.45


def test_evaluation_scores_ai_suggestions():
    def always_unknown(ev):
        return reply(category="UNKNOWN", explanation="No pattern fits this case.")

    rules = run_evaluation(days=2, breaks_per_day=6, seed=3)
    with_ai = run_evaluation(days=2, breaks_per_day=6, seed=3, ai_client=FakeClient(always_unknown))
    assert with_ai.detected == rules.detected  # the AI never changes detection
    assert with_ai.ai_accepted == with_ai.ai_calls == with_ai.cases
    assert with_ai.correct == 0
    assert with_ai.disagreements == with_ai.detected
    assert with_ai.disagreements_rules_right == rules.correct


def test_cli_with_ai_flag_but_no_key_runs_rules_only(tmp_path, capsys):
    assert main(["demo", "--dir", str(tmp_path), "--ai"]) == 0
    assert "no API key" in capsys.readouterr().err
    cases = load_cases(tmp_path / "run" / "cases.json")
    assert len(cases) == 12 and all(c.ai_status == "" for c in cases)
