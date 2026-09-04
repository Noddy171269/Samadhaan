"""Batch verification — proof the generated data showcases the FULL engine.

Runs the whole invoices.json batch through the real decide() at the batch's
reference date and confirms all five Actions appear at least once. If any is
missing, the generator failed to seed it. Also spot-checks the legal-correctness
invariant that MEDIUM vendors accrue zero interest even when chased.
"""

from collections import Counter

from engine import Action, decide, statutory_interest
from generate_data import REFERENCE_NOW, load_invoices


def summarize(now=REFERENCE_NOW):
    invoices = load_invoices()
    decisions = [decide(inv, now) for inv in invoices]
    counts = Counter(d.action for d in decisions)
    return invoices, decisions, counts


def test_all_five_actions_present():
    invoices, decisions, counts = summarize()

    # Every one of the five outcomes must be exercised by the batch.
    for action in Action:
        assert counts[action] >= 1, f"batch never produced {action.value}"

    # Correctness invariant: a MEDIUM vendor may be chased (FIRM_REMINDER) but
    # must never accrue statutory interest.
    by_id = {inv.id: inv for inv in invoices}
    for d in decisions:
        if by_id[d.invoice_id].vendor_class == "MEDIUM":
            assert d.interest_owed == 0.0, f"{d.invoice_id}: MEDIUM must accrue 0"

    # Where interest is charged, it must be strictly positive.
    for d in decisions:
        if d.action == Action.FIRM_REMINDER and by_id[d.invoice_id].vendor_class != "MEDIUM":
            assert d.interest_owed > 0, f"{d.invoice_id}: FIRM MSME should owe interest"


if __name__ == "__main__":
    invoices, decisions, counts = summarize()

    print(f"Batch: {len(invoices)} invoices, evaluated as of {REFERENCE_NOW}\n")
    print("Action histogram")
    print("-" * 40)
    for action in Action:
        print(f"  {action.value:18} {counts[action]:>3}")
    print("-" * 40)

    total_interest = sum(d.interest_owed for d in decisions)
    print(f"  {'total interest (INR)':18} {total_interest:>12,.2f}")

    missing = [a.value for a in Action if counts[a] == 0]
    if missing:
        print(f"\nMISSING outcomes: {missing} — fix the generator distribution.")
    else:
        test_all_five_actions_present()
        print("\nOK — all five actions present; MEDIUM interest is zero; MSME interest positive.")
