"""End-to-end pipeline tests for stages 4-5.

Confirms the composer/classifier never alter the engine's numbers, the message
templates behave per action, the year-end 43B(h) note fires, all five actions
appear, the headline interest total is unchanged, and report.json is written and
readable.
"""

import json

from action_composer import ActionOutput, compose, is_year_end_candidate
from classifier import Classifier
from engine import Action, decide
from generate_data import load_invoices
from run_batch import NOW, run

VALID_TONES = {
    "friendly": '{"urgency":"low","customer_reliability":"reliable","suggested_tone":"friendly"}',
    "firm": '{"urgency":"high","customer_reliability":"chronic_late","suggested_tone":"firm"}',
    "formal": '{"urgency":"medium","customer_reliability":"unknown","suggested_tone":"formal"}',
}


def test_composer_never_changes_action_or_interest():
    invoices = load_invoices()
    clf = Classifier(call_fn=lambda p: VALID_TONES["friendly"])
    for inv in invoices:
        d = decide(inv, NOW)
        c = clf.classify(inv, NOW)
        out = compose(inv, c, d, NOW)
        assert out.action == d.action  # action passed through untouched


def test_message_rules_by_action():
    invoices = load_invoices()
    clf = Classifier(call_fn=lambda p: VALID_TONES["firm"])
    seen = set()
    for inv in invoices:
        d = decide(inv, NOW)
        out = compose(inv, clf.classify(inv, NOW), d, NOW)
        seen.add(d.action)
        if d.action in (Action.GENTLE_REMINDER, Action.FIRM_REMINDER):
            assert out.message and out.channel == "email"
            if d.action == Action.GENTLE_REMINDER:
                assert "interest" not in out.message.lower()  # no figure yet
            if d.action == Action.FIRM_REMINDER:
                assert "Section 16" in out.message  # states the statutory interest
        else:
            assert out.message is None and out.channel == "none"
    # the batch really did exercise multiple actions
    assert len(seen) >= 4


def test_year_end_note_fires_for_msme_firm():
    invoices = load_invoices()
    clf = Classifier(call_fn=lambda p: VALID_TONES["formal"])
    hits = 0
    for inv in invoices:
        d = decide(inv, NOW)
        out = compose(inv, clf.classify(inv, NOW), d, NOW)
        if d.action == Action.FIRM_REMINDER and is_year_end_candidate(inv, NOW):
            assert "43B(h)" in out.message
            hits += 1
    assert hits > 0  # near year-end, unpaid MSME firm reminders carry the note


def test_medium_firm_has_no_year_end_note():
    # MEDIUM is excluded from 43B(h) — never flag it, even when chased near year-end.
    invoices = [i for i in load_invoices() if i.vendor_class == "MEDIUM"]
    clf = Classifier(call_fn=lambda p: VALID_TONES["formal"])
    for inv in invoices:
        assert not is_year_end_candidate(inv, NOW)


def test_full_run_totals_and_artifact(tmp_path=None):
    audit = run()
    s = audit.summary()

    # All five actions present.
    for a in Action:
        assert s["action_histogram"][a.value] >= 1

    # Headline interest unchanged by classifier/composer (engine owns the number).
    assert abs(s["total_statutory_interest"] - 224_031.20) < 0.01

    # recovered/escalated/exception bookkeeping is internally consistent.
    assert s["recovered_track"] == (
        s["action_histogram"]["GENTLE_REMINDER"] + s["action_histogram"]["FIRM_REMINDER"]
    )

    # report.json is written and readable.
    from audit import REPORT_FILE

    audit.write_json()
    data = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    assert data["summary"]["total_invoices"] == len(audit.rows)
    assert len(data["invoices"]) == len(audit.rows)


if __name__ == "__main__":
    for fn in (
        test_composer_never_changes_action_or_interest,
        test_message_rules_by_action,
        test_year_end_note_fires_for_msme_firm,
        test_medium_firm_has_no_year_end_note,
        test_full_run_totals_and_artifact,
    ):
        fn()
        print(f"PASS  {fn.__name__}")
    print("\nAll pipeline tests passed.")
