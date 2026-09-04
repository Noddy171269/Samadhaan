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
from dataclasses import dataclass
from datetime import date

# The classifier model. Named constant so it is trivially swappable; a cheap, fast
# call is all this needs. (Spec: claude-sonnet-4-6 or a similar current model.)
CLASSIFIER_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 150  # this is a short JSON reply — keep it cheap

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


class Classifier:
    """Wraps the single Anthropic call with a graceful fallback.

    The LLM call is injectable (`call_fn`) so tests can exercise the success and
    failure paths without a network or an API key.
    """

    def __init__(self, model: str = CLASSIFIER_MODEL, call_fn=None):
        self._model = model
        self._call_fn = call_fn or self._default_call
        self._client = None
        self._client_unavailable = False  # memoized: skip once we know it can't work

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

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self._client_unavailable:
            raise RuntimeError("classifier unavailable (no anthropic SDK or credentials)")
        # First real attempt: importing or constructing may fail (SDK absent, no key).
        # Memoize the failure so the remaining invoices fall back fast instead of
        # each re-attempting — one clean try, then a cheap short-circuit.
        try:
            import anthropic

            self._client = anthropic.Anthropic()
            return self._client
        except Exception:
            self._client_unavailable = True
            raise

    def _default_call(self, prompt: str) -> str:
        client = self._get_client()
        resp = client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")
