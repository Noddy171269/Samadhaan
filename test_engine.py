"""Differentiation proof for the Decision Engine.

Three invoices with the SAME amount and the SAME effective lateness (~50 days
past acceptance) that nonetheless produce THREE DIFFERENT actions — because the
reasoning underneath differs. This test is the demo's core claim, made concrete.
"""

from datetime import date, timedelta

from engine import Action, Invoice, decide

AMOUNT = 200_000.0
NOW = date(2026, 8, 31)
# ~50 days before NOW. With the 15-day statutory credit period, the appointed
# day lands ~34 days before NOW, so interest is live for the firm-reminder case.
ACCEPTANCE = NOW - timedelta(days=50)


def _base(**overrides) -> Invoice:
    """A clean SMALL-vendor invoice; override single fields per scenario."""
    fields = dict(
        id="INV",
        amount=AMOUNT,
        acceptance_date=ACCEPTANCE,
        has_written_agreement=False,
        agreed_terms_days=0,
        vendor_class="SMALL",
        disputed=False,
        prior_contacts=1,
    )
    fields.update(overrides)
    return Invoice(**fields)


def test_three_identical_invoices_diverge():
    # A: clean, MSME (SMALL), not disputed, chased once → firm reminder + interest.
    a = _base(id="A")
    # B: same lateness but disputed → routed to a human, no interest.
    b = _base(id="B", disputed=True)
    # C: same lateness but contact cap reached → stop and escalate, no interest.
    c = _base(id="C", prior_contacts=3)

    da = decide(a, NOW)
    db = decide(b, NOW)
    dc = decide(c, NOW)

    # Each lands on its intended action.
    assert da.action == Action.FIRM_REMINDER
    assert db.action == Action.ROUTE_TO_HUMAN
    assert dc.action == Action.STOP_AND_ESCALATE

    # Interest only where it is legally live.
    assert da.interest_owed > 0
    assert db.interest_owed == 0
    assert dc.interest_owed == 0

    # The differentiation proof: three identical-looking invoices, three actions.
    assert len({da.action, db.action, dc.action}) == 3

    # Every decision carries a reason.
    for d in (da, db, dc):
        assert d.reason


if __name__ == "__main__":
    test_three_identical_invoices_diverge()

    a = _base(id="A")
    b = _base(id="B", disputed=True)
    c = _base(id="C", prior_contacts=3)
    for inv in (a, b, c):
        d = decide(inv, NOW)
        print(
            f"{d.invoice_id}: {d.action.value:18} "
            f"interest={d.interest_owed:10.2f}  "
            f"appointed_day={d.appointed_day}  | {d.reason}"
        )
    print("\nOK — three identical invoices produced three different actions.")
