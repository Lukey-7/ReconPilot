"""Engine change 4: an OpenAI-compatible client for a private endpoint (no network in tests)."""

import pytest

from reconpilot import ai
from reconpilot.ai import (
    COMPATIBLE_ENV,
    AIError,
    OpenAICompatibleClient,
    make_client,
    make_compatible_client,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(ai.urllib.request, "urlopen", refuse)
    for var in [*ai.KEY_ENV.values(), *COMPATIBLE_ENV.values()]:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def transport(monkeypatch):
    """Stand in for ``_post_json``: records each request and answers with ``reply``."""
    sent = []
    state = {"reply": {"choices": [{"message": {"role": "assistant", "content": '{"category": "TIMING"}'}}]}}

    def fake(url, headers, body, timeout):
        sent.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return state["reply"]

    monkeypatch.setattr(ai, "_post_json", fake)
    return sent, state


def test_no_base_url_means_no_client():
    assert make_compatible_client() is None
    assert make_client("openai_compatible") is None


def test_never_chosen_automatically(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.internal.example/v1")
    assert make_client() is None  # no public key set: nothing is picked, the private endpoint included


def test_built_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.internal.example/v1/")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "house-model-7b")
    client = make_client("openai_compatible", effort="low", timeout=9)
    assert isinstance(client, OpenAICompatibleClient)
    assert (client.provider, client.model, client.effort, client.timeout) == (
        "openai_compatible", "house-model-7b", "low", 9)
    assert client.url() == "https://llm.internal.example/v1/chat/completions"
    assert client.headers() == {"Authorization": "Bearer sk-test"}
    # A model named by the caller wins over the environment's.
    assert make_client("openai_compatible", model="other").model == "other"


def test_azure_style_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL",
                       "https://bank.openai.azure.com/openai/deployments/recon-gpt")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "azure-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_VERSION", "2024-10-21")
    monkeypatch.setenv("OPENAI_COMPATIBLE_AUTH", "api-key")
    client = make_compatible_client()
    assert client.url() == (
        "https://bank.openai.azure.com/openai/deployments/recon-gpt/chat/completions?api-version=2024-10-21")
    assert client.headers() == {"api-key": "azure-key"}
    assert client.model == "default"


@pytest.mark.parametrize("var, value", [("OPENAI_COMPATIBLE_BASE_URL", "ftp://x"),
                                        ("OPENAI_COMPATIBLE_AUTH", "basic")])
def test_bad_configuration_is_refused(monkeypatch, var, value):
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://llm.internal.example/v1")
    monkeypatch.setenv(var, value)
    with pytest.raises(ValueError):
        make_compatible_client()


def test_self_hosted_without_a_key_sends_no_auth_header():
    client = OpenAICompatibleClient(base_url="http://127.0.0.1:11434/v1", model="llama")
    assert client.headers() == {}


def test_complete_sends_chat_completions_and_reads_the_answer(transport):
    sent, _ = transport
    client = OpenAICompatibleClient(base_url="https://llm.internal.example/v1", api_key="k", model="m1", timeout=5)
    assert client.complete("SYSTEM", "USER") == '{"category": "TIMING"}'
    (request,) = sent
    assert request["url"] == "https://llm.internal.example/v1/chat/completions"
    assert request["timeout"] == 5
    assert request["body"] == {
        "model": "m1",
        "messages": [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "USER"}],
        "response_format": {"type": "json_object"},
    }


@pytest.mark.parametrize("reply", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]},
                                   {"choices": [{"message": None}]}])
def test_unusable_answers_raise_ai_error(transport, reply):
    _, state = transport
    state["reply"] = reply
    client = OpenAICompatibleClient(base_url="https://llm.internal.example/v1")
    with pytest.raises(AIError):
        client.complete("s", "u")


def test_network_failure_becomes_ai_error(monkeypatch):
    def down(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(ai.urllib.request, "urlopen", down)
    client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    with pytest.raises(AIError, match="network error"):
        client.complete("s", "u")


def test_its_answers_go_through_the_same_guardrails(transport, tmp_path):
    """A whole case through ``assist_cases`` with the compatible client: accepted, audited with its provider."""
    from test_ai import reply, split_day

    from reconpilot.audit import AuditLog

    _, state = transport
    state["reply"] = {"choices": [{"message": {"content": reply()}}]}
    day, recon, cases = split_day()
    audit = AuditLog(tmp_path / "audit.jsonl")
    client = OpenAICompatibleClient(base_url="https://llm.internal.example/v1", model="house-1")
    ai.assist_cases(day, recon, cases, client, audit=audit)
    assert cases[0].ai_status == "ACCEPTED" and cases[0].ai_model == "house-1"
    entry = audit.entries()[-1]
    assert entry["action"] == "AI_CALL"
    assert entry["payload"]["provider"] == "openai_compatible" and entry["payload"]["model"] == "house-1"

    # An invented figure from the private endpoint is refused exactly as from any other.
    state["reply"] = {"choices": [{"message": {"content": reply(explanation="A gain of 12,345.67 USD.")}}]}
    day, recon, cases = split_day()
    ai.assist_cases(day, recon, cases, client, audit=audit)
    assert cases[0].ai_status == "FALLBACK"


def test_command_line_offers_the_private_endpoint(tmp_path, capsys):
    """``--ai-provider openai_compatible`` is accepted; with no base URL set it falls back to the rules."""
    from reconpilot.cli import main
    from reconpilot.storage import load_cases

    assert main(["demo", "--dir", str(tmp_path), "--ai", "--ai-provider", "openai_compatible"]) == 0
    assert "no API key" in capsys.readouterr().err
    cases = load_cases(tmp_path / "run" / "cases.json")
    assert cases and all(c.ai_status == "" for c in cases)
