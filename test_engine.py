"""Differentiation proof for the Decision Engine.

Three invoices with the SAME amount and the SAME effective lateness (~50 days
past the appointed day) that nonetheless produce THREE DIFFERENT actions —
because the reasoning underneath differs. This test is the demo's core claim,
made concrete. It also proves the interest calc is now day-accurate, not
whole-month-only.
"""

from datetime import date

from engine import Action, Invoice, decide, statutory_interest

AMOUNT = 200_000.0
NOW = date(2026, 7, 21)

# With no written agreement, appointed_day = acceptance + 16 days.
# ACCEPTANCE_50 -> appointed 2026-06-01 -> 50 days overdue = 1 month + 20 days.
ACCEPTANCE_50 = date(2026, 5, 16)
# ACCEPTANCE_31 -> appointed 2026-06-20 -> 31 days overdue = 1 month +  1 day.
ACCEPTANCE_31 = date(2026, 6, 4)

# Day-accurate expected interest for A (principal 200000, 3x5.50% = 16.5%):
#   after 1 month: 200000 * 1.01375          = 202750.00
#   leftover 20d:  202750 * (0.165/365) * 20 =   1833.08
#   total interest                           =   4583.08
EXPECTED_A_INTEREST = 4583.08
# What the OLD whole-month-only method would have reported (proof we improved on it):
WHOLE_MONTH_ONLY = AMOUNT * 1.01375 - AMOUNT  # = 2750.00


def _base(**overrides) -> Invoice:
    """A clean SMALL-vendor invoice ~50 days overdue; override fields per scenario."""
    fields = dict(
        id="INV",
        amount=AMOUNT,
        acceptance_date=ACCEPTANCE_50,
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

    # Day-accurate figure, hand-verifiable, and strictly ABOVE the old
    # whole-month-only figure — proving leftover days are now counted.
    assert abs(da.interest_owed - EXPECTED_A_INTEREST) < 1.0
    assert da.interest_owed > WHOLE_MONTH_ONLY

    # The differentiation proof: three identical-looking invoices, three actions.
    assert len({da.action, db.action, dc.action}) == 3

    # Every decision carries a reason.
    for d in (da, db, dc):
        assert d.reason


def test_31_and_50_days_differ():
    """31-day and 50-day overdue invoices used to collapse to the same "1 month".

    With day-accurate accrual they must now produce DIFFERENT interest.
    """
    inv_31 = _base(id="D31", acceptance_date=ACCEPTANCE_31)
    inv_50 = _base(id="D50", acceptance_date=ACCEPTANCE_50)

    i31 = statutory_interest(inv_31, NOW)
    i50 = statutory_interest(inv_50, NOW)

    assert i31 > 0
    assert i50 > i31  # more days overdue → strictly more interest
    assert i31 != i50  # they no longer collapse to an identical figure


if __name__ == "__main__":
    test_three_identical_invoices_diverge()
    test_31_and_50_days_differ()

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

    print(
        "\n31 vs 50 days overdue: "
        f"{statutory_interest(_base(acceptance_date=ACCEPTANCE_31), NOW):.2f} "
        f"!= {statutory_interest(_base(acceptance_date=ACCEPTANCE_50), NOW):.2f}"
    )
    print("\nOK — three identical invoices produced three different actions,")
    print("     and interest is now day-accurate (leftover days counted).")
