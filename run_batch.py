"""Single entry point — the whole pipeline in one command.

    load (stage 1) -> classify (stage 2) -> decide (stage 3) -> compose (stage 4)
    -> record + report (stage 5)

The engine decides the action; the classifier only annotates and the composer only
words. Run with an ANTHROPIC_API_KEY set to see real LLM classifications in the
report's coverage line; without one, every invoice cleanly falls back and the batch
still completes end to end.
"""

from datetime import date

from action_composer import compose
from audit import Audit
from classifier import Classifier
from engine import decide
from generate_data import load_invoices

# Single reference date for the whole run. The batch was built around 20 Mar 2026
# (near the 31 Mar fiscal year-end) so the 43B(h) year-end cases fire. Change here.
NOW = date(2026, 3, 20)


def run() -> Audit:
    invoices = load_invoices()
    classifier = Classifier()
    audit = Audit()

    for inv in invoices:
        classification = classifier.classify(inv, NOW)  # stage 2 — advisory only
        decision = decide(inv, NOW)                      # stage 3 — the action
        output = compose(inv, classification, decision, NOW)  # stage 4 — the wording
        audit.record(inv, classification, decision, output)   # stage 5

    return audit


if __name__ == "__main__":
    audit = run()
    audit.print_report()
    audit.write_json()
    print("\nWrote report.json")
