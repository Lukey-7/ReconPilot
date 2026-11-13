"""AI-assisted triage and investigation on top of the deterministic engine.

The matching engine, tolerances, NAV checks, review and audit log stay
deterministic. This module only adds a second opinion on each case: a large
language model reads the evidence the engine has already gathered and returns
a suggested cause, an explanation, investigation steps and a draft query.

Everything the model says passes through guardrails before anyone sees it:

* the response must match a strict JSON schema, and the category must be one
  of the existing ``Category`` values;
* every figure quoted in the explanation must appear in the evidence it was
  given, so it cannot invent amounts;
* if it disagrees with the rule-based suggestion, both are kept and the case
  is flagged for review;
* on any error, timeout, invalid response or missing API key, the case keeps
  the rule-based output unchanged.

Every call is written to the hash-chained audit log with the model, the
prompt hash, the raw response and whether the fallback was used. Responses
are cached on disk by prompt hash, so re-running an evaluation is free and
gives the same answers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reconpilot.audit import AuditLog
from reconpilot.matching import ReconResult
from reconpilot.models import BASE_CURRENCY, BreakKind, Case, Category, DayData

PROMPT_VERSION = "2026-11-14.1"
DISAGREEMENT_FLAG = "AI disagrees: needs review"

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-6-luna",
    "google": "gemini-3.8-flash",
}
KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category", "confidence", "explanation", "investigation_steps", "custodian_query"],
    "properties": {
        "category": {"type": "string", "enum": [c.value for c in Category]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 2000},
        "investigation_steps": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1, "maxLength": 400},
        },
        "custodian_query": {"type": "string", "minLength": 1, "maxLength": 3000},
    },
}

SYSTEM_PROMPT = """\
You assist a fund operations analyst with the daily reconciliation of a fund's
books against its custodian. You receive the evidence for one exception case as
JSON. The matching engine that produced the evidence is deterministic and its
figures are correct. Your job is to judge the most likely root cause, explain it,
suggest how to investigate, and draft a query to the custodian. A person reviews
everything you write before anything is acted on.

Choose exactly one category:
- MISSING_TRADE: a trade one side has and the other has no record of at all,
  typically a trade the custodian has settled (position and cash moved) that the
  fund never booked.
- TIMING: a trade the fund booked that has not settled at the custodian on its
  due date (a late or failed settlement). The custodian may show it as pending
  with a later value date, or may not report it yet.
- PRICE_MISMATCH: quantities agree but the custodian's price differs.
- STOCK_SPLIT: quantity and price have moved by the same whole-number factor in
  opposite directions, so the market value is roughly unchanged (a split or
  reverse split processed by one side only).
- DIVIDEND: income the custodian has credited that the fund has not accrued.
  Custodians sometimes post income with no security identifier and a vague
  narrative such as "CREDIT" or "MISC RECEIPT"; judge it from the sign, the size,
  the absence of any position difference and the absence of a related trade.
- FX_DIFFERENCE: a foreign-currency trade settled for a different base-currency
  amount because a different exchange rate was applied; quantity and price agree.
- UNKNOWN: none of the above fits the evidence.

The rule-based suggestion is included. Agree with it when the evidence supports
it; disagree only when the evidence points elsewhere, and say why.

Read the custodian narrative text on cash lines; it often carries the answer.

Figures: quote numbers exactly as they appear in the evidence. You may add
thousands separators, drop trailing zeros or round to fewer decimal places, but
never calculate or state a figure that is not in the evidence. The "derived"
section already contains the useful differences and ratios.

Reply with a single JSON object and nothing else:
{
  "category": one of the categories above,
  "confidence": number from 0 to 1,
  "explanation": two to four sentences quoting the relevant figures,
  "investigation_steps": two to four short, concrete steps,
  "custodian_query": a short, polite email to the custodian, starting with "Subject: "
}
"""


class AIError(Exception):
    """Raised when a response cannot be used; the case falls back to the rules."""


class LLMClient(Protocol):
    provider: str
    model: str
    effort: str

    def complete(self, system: str, user: str) -> str: ...


# --------------------------------------------------------------------------- providers


def _post_json(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise AIError(f"HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIError(f"network error: {exc}") from None


@dataclass
class AnthropicClient:
    api_key: str
    model: str = DEFAULT_MODELS["anthropic"]
    effort: str = "medium"
    timeout: float = 120.0
    provider: str = "anthropic"

    def complete(self, system: str, user: str) -> str:
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            {
                "model": self.model,
                "max_tokens": 4096,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            self.timeout,
        )
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if not text:
            raise AIError("empty response")
        return text


@dataclass
class OpenAIClient:
    api_key: str
    model: str = DEFAULT_MODELS["openai"]
    effort: str = "medium"
    timeout: float = 120.0
    provider: str = "openai"

    def complete(self, system: str, user: str) -> str:
        data = _post_json(
            "https://api.openai.com/v1/responses",
            {"Authorization": f"Bearer {self.api_key}"},
            {
                "model": self.model,
                "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "reasoning": {"effort": self.effort},
                "text": {"format": {"type": "json_object"}},
            },
            self.timeout,
        )
        parts = [
            c.get("text", "")
            for item in data.get("output", [])
            if item.get("type") == "message"
            for c in item.get("content") or []
            if c.get("type") == "output_text"
        ]
        if not parts:
            raise AIError("empty response")
        return "".join(parts)


@dataclass
class GoogleClient:
    api_key: str
    model: str = DEFAULT_MODELS["google"]
    effort: str = "medium"
    timeout: float = 120.0
    provider: str = "google"

    def complete(self, system: str, user: str) -> str:
        data = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            {"x-goog-api-key": self.api_key},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingLevel": self.effort},
                },
            },
            self.timeout,
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            raise AIError(f"no candidates in response: {json.dumps(data)[:300]}") from None
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise AIError("empty response")
        return text


_CLIENTS = {"anthropic": AnthropicClient, "openai": OpenAIClient, "google": GoogleClient}


def make_client(
    provider: str | None = None,
    model: str | None = None,
    effort: str = "medium",
    timeout: float = 120.0,
) -> LLMClient | None:
    """Build a client from environment keys. Returns None when no key is set.

    With no provider given, the first provider with a key wins, in the order
    Anthropic, OpenAI, Google.
    """
    order = [provider] if provider else list(KEY_ENV)
    for name in order:
        if name not in _CLIENTS:
            raise ValueError(f"unknown provider {name!r}; choose from {', '.join(_CLIENTS)}")
        key = os.environ.get(KEY_ENV[name], "").strip()
        if key:
            return _CLIENTS[name](api_key=key, model=model or DEFAULT_MODELS[name], effort=effort, timeout=timeout)
    return None


# --------------------------------------------------------------------------- evidence


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(float(x), nd)


def build_evidence(day: DayData, recon: ReconResult, case: Case) -> dict:
    """Everything the model may rely on for one case, and nothing else."""
    breaks = [b for b in recon.breaks if b.break_id in set(case.break_ids)]
    sid = case.security_id
    sec = day.securities.get(sid)
    ccy = sec.currency if sec else BASE_CURRENCY
    fx = day.fx_rates.get(ccy, 1.0)
    refs = {b.reference for b in breaks if b.reference}
    pos = day.book_positions.get(sid)
    hold = day.custodian_holdings.get(sid)

    trades = [t for t in day.book_trades if (sid and t.security_id == sid) or t.trade_id in refs]
    settled = [ln for ln in day.custodian_cash if ln.value_date == day.as_of]
    cash_lines = [ln for ln in settled if (sid and ln.security_id == sid) or ln.reference in refs or ln.entry_id in refs]
    pending = [ln for ln in recon.pending if (sid and ln.security_id == sid) or ln.reference in refs]
    narrative = {ln.entry_id: ln.description for ln in day.custodian_cash}

    derived: dict[str, float | None] = {}
    by_kind = {k: [b for b in breaks if b.kind is k] for k in BreakKind}
    qty = by_kind[BreakKind.QUANTITY][0] if by_kind[BreakKind.QUANTITY] else None
    price = by_kind[BreakKind.PRICE][0] if by_kind[BreakKind.PRICE] else None
    unit_price = pos.price if pos and pos.price > 0 else (hold.price if hold else 0.0)
    if qty:
        derived["quantity_gap_custodian_minus_book"] = _r(qty.custodian_value - qty.book_value, 2)
        if qty.book_value:
            derived["quantity_ratio_custodian_to_book"] = _r(qty.custodian_value / qty.book_value, 6)
        derived["value_of_quantity_gap_base"] = _r(abs(qty.custodian_value - qty.book_value) * unit_price * fx, 2)
    if price and price.book_value:
        derived["price_difference_pct"] = _r((price.custodian_value - price.book_value) / price.book_value * 100, 4)
        derived["price_ratio_book_to_custodian"] = _r(price.book_value / price.custodian_value, 6)
    unmatched_in_book = by_kind[BreakKind.CASH_MISSING_IN_BOOK]
    if unmatched_in_book:
        total = sum(b.custodian_value or 0 for b in unmatched_in_book)
        derived["custodian_cash_not_in_book_total"] = _r(total, 2)
        held = (hold.quantity if hold else 0) or (pos.quantity if pos else 0)
        if held and sid:
            derived["amount_per_unit_held_local_ccy"] = _r(total / (held * fx), 4)
    unmatched_at_cust = by_kind[BreakKind.CASH_MISSING_AT_CUSTODIAN]
    if unmatched_at_cust:
        derived["book_cash_not_at_custodian_total"] = _r(sum(b.book_value or 0 for b in unmatched_at_cust), 2)
    for b in by_kind[BreakKind.CASH_AMOUNT]:
        trade = next((t for t in day.book_trades if t.trade_id == b.reference), None)
        derived["cash_difference"] = _r(b.difference, 2)
        if trade:
            book_gross = abs(b.book_value + trade.fees)
            cust_gross = abs(b.custodian_value + trade.fees)
            rel = cust_gross / book_gross - 1 if book_gross else 0.0
            derived["cash_difference_pct_of_gross"] = _r(rel * 100, 4)
            derived["implied_custodian_fx_rate"] = _r(trade.fx_rate * (1 + rel), 6)

    return {
        "as_of": str(day.as_of),
        "base_currency": BASE_CURRENCY,
        "case_id": case.case_id,
        "security": (
            {"security_id": sid, "name": sec.name, "currency": ccy, "base_per_unit_fx": fx}
            if sec else {"security_id": sid or None, "note": "custodian gave no security identifier"}
        ),
        "book_position": (
            {"quantity": pos.quantity, "price": pos.price, "price_date": str(pos.price_date)} if pos else None
        ),
        "custodian_holding": {"quantity": hold.quantity, "price": hold.price} if hold else None,
        "breaks": [
            {
                "break_id": b.break_id,
                "kind": b.kind.value,
                "book_value": b.book_value,
                "custodian_value": b.custodian_value,
                "difference": _r(b.difference, 6),
                "reference": b.reference,
                "custodian_narrative": b.note or None,
            }
            for b in breaks
        ],
        "book_trades": [
            {
                "trade_id": t.trade_id, "trade_date": str(t.trade_date), "settle_date": str(t.settle_date),
                "side": t.side.value, "quantity": t.quantity, "price": t.price, "currency": t.currency,
                "fx_rate": t.fx_rate, "fees": t.fees, "settlement_cash_base": t.cash_amount,
            }
            for t in trades
        ],
        "custodian_cash_settled_today": [
            {"entry_id": ln.entry_id, "reference": ln.reference, "amount": ln.amount,
             "narrative": narrative[ln.entry_id]}
            for ln in cash_lines
        ],
        "custodian_cash_pending": [
            {"entry_id": ln.entry_id, "value_date": str(ln.value_date), "reference": ln.reference,
             "amount": ln.amount, "narrative": ln.description}
            for ln in pending
        ],
        "derived": derived,
        "rule_based_suggestion": {
            "category": case.category.value,
            "confidence": case.confidence,
            "explanation": case.explanation,
        },
        "allowed_categories": [c.value for c in Category],
    }


def build_prompt(evidence: dict) -> str:
    return "Evidence for this case:\n\n" + json.dumps(evidence, indent=2, sort_keys=True)


def prompt_hash(client: LLMClient, system: str, user: str) -> str:
    key = "\x1f".join([PROMPT_VERSION, client.provider, client.model, client.effort, system, user])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- guardrails


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


def validate_response(text: str) -> dict:
    """Parse and check a response against RESPONSE_SCHEMA. Raises AIError."""
    try:
        data = json.loads(_strip_fences(text))
    except (json.JSONDecodeError, TypeError) as exc:
        raise AIError(f"malformed JSON: {exc}") from None
    if not isinstance(data, dict):
        raise AIError("response is not a JSON object")
    props = RESPONSE_SCHEMA["properties"]
    missing = [k for k in RESPONSE_SCHEMA["required"] if k not in data]
    if missing:
        raise AIError(f"missing fields: {', '.join(missing)}")
    extra = sorted(set(data) - set(props))
    if extra:
        raise AIError(f"unexpected fields: {', '.join(extra)}")
    if data["category"] not in props["category"]["enum"]:
        raise AIError(f"category {data['category']!r} is not an allowed value")
    conf = data["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
        raise AIError(f"confidence {conf!r} is not a number between 0 and 1")
    for field in ("explanation", "custodian_query"):
        value = data[field]
        spec = props[field]
        if not isinstance(value, str) or not value.strip() or len(value) > spec["maxLength"]:
            raise AIError(f"{field} must be a non-empty string under {spec['maxLength']} characters")
    steps = data["investigation_steps"]
    spec = props["investigation_steps"]
    if not isinstance(steps, list) or not spec["minItems"] <= len(steps) <= spec["maxItems"]:
        raise AIError("investigation_steps must be a list of 2 to 4 items")
    if not all(isinstance(s, str) and s.strip() and len(s) <= 400 for s in steps):
        raise AIError("each investigation step must be a non-empty string")
    return data


_IDENT = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*\d[A-Za-z0-9_-]*")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?(%?)")


def _numbers_in(value) -> list[float]:
    out: list[float] = []
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        text = _DATE.sub(" ", _IDENT.sub(" ", value))
        for m in _NUMBER.finditer(text):
            try:
                out.append(float(m.group(0).rstrip("%").replace(",", "")))
            except ValueError:
                pass
        return out
    if isinstance(value, dict):
        for v in value.values():
            out.extend(_numbers_in(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_numbers_in(v))
    return out


def unsupported_figures(explanation: str, evidence: dict) -> list[str]:
    """Return figures in ``explanation`` that cannot be traced to ``evidence``.

    A quoted figure is accepted if it equals an evidence value after rounding
    to the number of decimals it is quoted with (signs ignored). Percentages
    may also be quoted as fractions, and small counts (0 to 10) are allowed.
    """
    known = [abs(x) for x in _numbers_in(evidence)]
    text = _DATE.sub(" ", _IDENT.sub(" ", explanation))
    bad = []
    for m in _NUMBER.finditer(text):
        raw = m.group(0)
        body = raw.rstrip("%").replace(",", "").lstrip("+-")
        try:
            x = float(body)
        except ValueError:
            continue
        if x <= 10 and body.isdigit():
            continue
        decimals = len(body.split(".")[1]) if "." in body else 0
        tol = 0.5 * 10 ** -decimals + 1e-9
        candidates = [(x, tol)] + ([(x / 100, tol / 100)] if raw.endswith("%") else [])
        if not any(abs(c - k) <= t for c, t in candidates for k in known):
            bad.append(raw)
    return bad


# --------------------------------------------------------------------------- cache


class ResponseCache:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)

    def get(self, key: str) -> str | None:
        path = self.folder / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        except (OSError, ValueError, KeyError):
            return None

    def put(self, key: str, provider: str, model: str, response: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        payload = {"provider": provider, "model": model, "prompt_version": PROMPT_VERSION, "response": response}
        (self.folder / f"{key}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- orchestration


@dataclass
class _Call:
    case: Case
    evidence: dict
    key: str
    response: str | None = None
    cached: bool = False
    error: str | None = None


def _fetch(call: _Call, client: LLMClient, user: str, cache: ResponseCache | None) -> _Call:
    if cache is not None:
        hit = cache.get(call.key)
        if hit is not None:
            call.response, call.cached = hit, True
            return call
    try:
        call.response = client.complete(SYSTEM_PROMPT, user)
    except AIError as exc:
        call.error = str(exc)
        return call
    except Exception as exc:  # never let one bad call break the run
        call.error = f"{type(exc).__name__}: {exc}"
        return call
    if cache is not None:
        cache.put(call.key, client.provider, client.model, call.response)
    return call


def apply_response(case: Case, evidence: dict, response: str, model: str) -> None:
    """Validate a response and copy it onto the case. Raises AIError if unusable."""
    data = validate_response(response)
    bad = unsupported_figures(data["explanation"], evidence)
    if bad:
        raise AIError(f"explanation quotes figures not in the evidence: {', '.join(bad)}")
    case.ai_category = Category(data["category"])
    case.ai_confidence = round(float(data["confidence"]), 2)
    case.ai_explanation = data["explanation"].strip()
    case.ai_steps = [s.strip() for s in data["investigation_steps"]]
    case.ai_query = data["custodian_query"].strip()
    case.ai_model = model
    case.ai_status = "ACCEPTED"
    case.ai_flag = DISAGREEMENT_FLAG if case.ai_category is not case.category else ""


def _fallback(case: Case, model: str, reason: str) -> None:
    case.ai_category = None
    case.ai_confidence = None
    case.ai_explanation = ""
    case.ai_steps = []
    case.ai_query = ""
    case.ai_model = model
    case.ai_status = "FALLBACK"
    case.ai_flag = ""
    case.ai_fallback_reason = reason


def assist_cases(
    day: DayData,
    recon: ReconResult,
    cases: list[Case],
    client: LLMClient | None,
    audit: AuditLog | None = None,
    actor: str = "system",
    role: str = "analyst",
    cache: ResponseCache | None = None,
    max_workers: int = 8,
) -> list[Case]:
    """Add AI suggestions to ``cases`` in place. Rule-based fields are never changed."""
    if client is None:
        if audit is not None:
            audit.append(actor, role, "AI_UNAVAILABLE", {"reason": "no API key set", "cases": len(cases)})
        return cases

    calls = []
    users = {}
    for case in cases:
        evidence = build_evidence(day, recon, case)
        user = build_prompt(evidence)
        call = _Call(case, evidence, prompt_hash(client, SYSTEM_PROMPT, user))
        users[case.case_id] = user
        calls.append(call)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        done = list(pool.map(lambda c: _fetch(c, client, users[c.case.case_id], cache), calls))

    for call in done:  # sequential, so audit entries stay in order
        reason = call.error
        if reason is None:
            try:
                apply_response(call.case, call.evidence, call.response, client.model)
            except AIError as exc:
                reason = str(exc)
        if reason is not None:
            _fallback(call.case, client.model, reason)
        if audit is not None:
            audit.append(actor, role, "AI_CALL", {
                "case_id": call.case.case_id,
                "provider": client.provider,
                "model": client.model,
                "effort": client.effort,
                "prompt_version": PROMPT_VERSION,
                "prompt_hash": call.key,
                "cached": call.cached,
                "response": call.response,
                "fallback_used": reason is not None,
                "fallback_reason": reason,
                "rule_category": call.case.category.value,
                "ai_category": call.case.ai_category.value if call.case.ai_category else None,
                "disagrees": bool(call.case.ai_flag),
            })
    return cases
