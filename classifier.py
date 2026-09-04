"""LLM classifier — the ONLY place an LLM is used in this project.

The classifier ANNOTATES; it does not DECIDE. It reads an invoice's situation and
returns advisory metadata (urgency, reliability, suggested tone) that later stages
use to shape reminder WORDING and to enrich the audit log. It never feeds decide().
If this whole file were deleted, decide() would still produce byte-identical
actions — the engine imports nothing from here, and no field below is control flow.
That separation is the project's thesis.

Failure is graceful by design: one clean call, one fallback. On any error — network,
bad JSON, missing field, missing API key — a safe default is returned marked
source="fallback", so the batch always completes and the audit report can honestly
state how many invoices used the model versus the fallback.
"""

import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import date

# The classifier model. Named constant so it is trivially swappable; a cheap, fast
# call is all this needs. (Spec: claude-sonnet-4-6 or a similar current model.)
CLASSIFIER_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 150  # this is a short JSON reply — keep it cheap

# Free-tier fallback providers, so the LLM path can be demonstrated without setting
# up Anthropic billing. Anthropic remains the preferred provider; these are used only
# when no ANTHROPIC_API_KEY is present. NOTE: using a non-Anthropic model is a
# deliberate departure from CLAUDE.md's "Anthropic API" design, made purely to show a
# live classification for free — disclose it in the writeup. Models are env-overridable.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
_HTTP_TIMEOUT = 30  # seconds — one shot, no retries

_URGENCY = {"low", "medium", "high"}
_RELIABILITY = {"reliable", "chronic_late", "unknown"}
_TONE = {"friendly", "firm", "formal"}


@dataclass(frozen=True)
class Classification:
    """Advisory read of an invoice's situation. NOT read by the decision engine."""

    urgency: str  # "low" | "medium" | "high"
    customer_reliability: str  # "reliable" | "chronic_late" | "unknown"
    suggested_tone: str  # "friendly" | "firm" | "formal"
    source: str  # "llm" | "fallback" — so the audit log shows which model was used


# The safe default used whenever the LLM path fails for any reason.
FALLBACK = Classification(
    urgency="medium",
    customer_reliability="unknown",
    suggested_tone="firm",
    source="fallback",
)


def _build_prompt(invoice, as_of: date) -> str:
    days_since_acceptance = (as_of - invoice.acceptance_date).days
    return (
        "Assess this overdue invoice's situation. Respond with ONLY a JSON object,\n"
        "no other text, matching exactly:\n"
        '{"urgency":"low|medium|high",'
        '"customer_reliability":"reliable|chronic_late|unknown",'
        '"suggested_tone":"friendly|firm|formal"}\n\n'
        f"Invoice: amount={invoice.amount}, "
        f"days_since_acceptance={days_since_acceptance}, "
        f"prior_contacts={invoice.prior_contacts}, "
        f"vendor_class={invoice.vendor_class}, "
        f"has_written_agreement={invoice.has_written_agreement}"
    )


def _strip_fences(text: str) -> str:
    """Remove a leading ```json / ``` fence and a trailing ``` fence, if present."""
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").strip()
    text = text.removesuffix("```").strip()
    return text


def _parse(raw: str) -> Classification:
    """Parse and VALIDATE the model's reply. Raises on anything malformed."""
    data = json.loads(_strip_fences(raw))
    urgency = data["urgency"]
    reliability = data["customer_reliability"]
    tone = data["suggested_tone"]
    if urgency not in _URGENCY or reliability not in _RELIABILITY or tone not in _TONE:
        raise ValueError(f"classifier returned out-of-range values: {data}")
    return Classification(urgency, reliability, tone, source="llm")


def active_provider() -> str | None:
    """Which LLM provider is configured right now, by which key is set (or None).

    Anthropic is preferred; the free-tier providers are used only as alternates.
    Read at call time so setting a key in the shell takes effect immediately.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return None


def _http_post_json(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={**headers, "Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_groq(prompt: str) -> str:
    # Groq's OpenAI-compatible endpoint. Key goes in the Authorization header.
    resp = _http_post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        },
    )
    return resp["choices"][0]["message"]["content"]


def _call_gemini(prompt: str) -> str:
    # Gemini: key in the x-goog-api-key header (never in the URL query string).
    resp = _http_post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        {"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": 0},
        },
    )
    return resp["candidates"][0]["content"]["parts"][0]["text"]


class Classifier:
    """Wraps a single LLM call with a graceful fallback.

    Provider is chosen by which API key is set (Anthropic preferred, then the free
    Groq / Gemini tiers). The LLM call is injectable (`call_fn`) so tests can
    exercise the success and failure paths without a network or an API key.
    """

    def __init__(self, model: str = CLASSIFIER_MODEL, call_fn=None):
        self._model = model
        self._call_fn = call_fn or self._default_call
        self._anthropic_client = None

    def classify(self, invoice, as_of: date) -> Classification:
        """Annotate one invoice. Never raises — any failure yields FALLBACK."""
        prompt = _build_prompt(invoice, as_of)
        try:
            raw = self._call_fn(prompt)
            return _parse(raw)
        except Exception:
            return FALLBACK

    def classify_batch(self, invoices, as_of: date) -> list[Classification]:
        return [self.classify(inv, as_of) for inv in invoices]

    # --- the real LLM call (skipped entirely when injected) ---

    def _default_call(self, prompt: str) -> str:
        provider = active_provider()
        if provider == "anthropic":
            return self._call_anthropic(prompt)
        if provider == "groq":
            return _call_groq(prompt)
        if provider == "gemini":
            return _call_gemini(prompt)
        raise RuntimeError("no LLM provider configured (set ANTHROPIC_API_KEY / GROQ_API_KEY / GEMINI_API_KEY)")

    def _call_anthropic(self, prompt: str) -> str:
        if self._anthropic_client is None:
            import anthropic

            self._anthropic_client = anthropic.Anthropic()
        resp = self._anthropic_client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")
