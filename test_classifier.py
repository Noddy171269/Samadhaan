"""Tests for the LLM classifier — success path, fallback path, batch completion.

No network required: the LLM call is injected, so valid and broken responses are
simulated deterministically. Also confirms the iron rule — the classifier's output
never changes the engine's action.
"""

import os

from generate_data import REFERENCE_NOW, load_invoices
from classifier import FALLBACK, Classification, Classifier, active_provider
from engine import decide

VALID = '{"urgency":"high","customer_reliability":"chronic_late","suggested_tone":"firm"}'


def _one_invoice():
    return load_invoices()[0]


def test_valid_json_parses_as_llm():
    clf = Classifier(call_fn=lambda prompt: VALID)
    c = clf.classify(_one_invoice(), REFERENCE_NOW)
    assert isinstance(c, Classification)
    assert c.source == "llm"
    assert (c.urgency, c.customer_reliability, c.suggested_tone) == (
        "high",
        "chronic_late",
        "firm",
    )


def test_markdown_fenced_json_parses():
    clf = Classifier(call_fn=lambda prompt: f"```json\n{VALID}\n```")
    c = clf.classify(_one_invoice(), REFERENCE_NOW)
    assert c.source == "llm"
    assert c.urgency == "high"


def test_missing_field_falls_back():
    # A deliberately broken response (missing two fields) must fall back.
    clf = Classifier(call_fn=lambda prompt: '{"urgency":"high"}')
    c = clf.classify(_one_invoice(), REFERENCE_NOW)
    assert c == FALLBACK
    assert c.source == "fallback"


def test_out_of_range_value_falls_back():
    clf = Classifier(
        call_fn=lambda prompt: '{"urgency":"nuclear","customer_reliability":"unknown","suggested_tone":"firm"}'
    )
    c = clf.classify(_one_invoice(), REFERENCE_NOW)
    assert c.source == "fallback"


def test_raising_call_falls_back():
    # Simulates a bad key / network error: the call itself raises.
    def boom(prompt):
        raise RuntimeError("401 authentication_error")

    clf = Classifier(call_fn=boom)
    c = clf.classify(_one_invoice(), REFERENCE_NOW)
    assert c.source == "fallback"


def test_batch_completes_with_default_classifier():
    # The REAL classifier: with no API key/SDK it must cleanly fall back for every
    # invoice and still return one Classification each — the batch never crashes.
    clf = Classifier()
    invoices = load_invoices()[:5]
    results = clf.classify_batch(invoices, REFERENCE_NOW)
    assert len(results) == len(invoices)
    for r in results:
        assert r.source in ("llm", "fallback")
        assert r.urgency in ("low", "medium", "high")


def test_active_provider_prefers_anthropic_then_free_tiers():
    saved = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        assert active_provider() is None  # nothing set → fall back

        os.environ["GEMINI_API_KEY"] = "x"
        assert active_provider() == "gemini"
        os.environ["GROQ_API_KEY"] = "x"
        assert active_provider() == "groq"  # groq outranks gemini
        os.environ["ANTHROPIC_API_KEY"] = "x"
        assert active_provider() == "anthropic"  # anthropic preferred
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_classification_does_not_change_engine_action():
    # Iron rule: whatever the classifier says, decide() is unaffected — it takes no
    # classification at all. Same action with wildly different annotations.
    inv = _one_invoice()
    baseline = decide(inv, REFERENCE_NOW).action
    for fake in (
        '{"urgency":"low","customer_reliability":"reliable","suggested_tone":"friendly"}',
        '{"urgency":"high","customer_reliability":"chronic_late","suggested_tone":"formal"}',
    ):
        Classifier(call_fn=lambda prompt, r=fake: r).classify(inv, REFERENCE_NOW)
        assert decide(inv, REFERENCE_NOW).action == baseline


if __name__ == "__main__":
    for fn in (
        test_valid_json_parses_as_llm,
        test_markdown_fenced_json_parses,
        test_missing_field_falls_back,
        test_out_of_range_value_falls_back,
        test_raising_call_falls_back,
        test_batch_completes_with_default_classifier,
        test_active_provider_prefers_anthropic_then_free_tiers,
        test_classification_does_not_change_engine_action,
    ):
        fn()
        print(f"PASS  {fn.__name__}")

    # Honest source count over a sample, exactly as the audit report will show it.
    clf = Classifier()
    sample = load_invoices()[:5]
    results = clf.classify_batch(sample, REFERENCE_NOW)
    llm = sum(1 for r in results if r.source == "llm")
    fb = sum(1 for r in results if r.source == "fallback")
    print(f"\nSample of {len(sample)}: {llm} used LLM, {fb} used fallback.")
