"""Decision Engine — the deterministic "brain" of the Receivables Agent.

No LLM lives here. This module applies the law (MSMED Act 2006) and the
conduct rules to pick a single, bounded recovery action for one invoice, and
attaches a human-readable reason to every decision. Safety gates (dispute,
contact cap) run BEFORE any recovery or interest logic — that ordering is the
whole point and must not be reordered.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from dateutil.relativedelta import relativedelta

# --- Named, auditable constants -------------------------------------------

# RBI bank rate used for MSMED Section 16 statutory interest (3x this rate).
# THIS CHANGES over time and must be verified/updated against the current RBI
# published bank rate before any real run. ~5.50% as of this build.
RBI_BANK_RATE = 0.055

# Voluntary conduct ceiling (borrowed from the RBI Fair Practices Code):
# number of automated contacts allowed before mandatory human escalation.
MAX_AUTO_CONTACTS = 3

# Statutory credit period (in days) when there is no written agreement.
STATUTORY_CREDIT_DAYS = 15

# The law voids any agreed credit period longer than this; we clamp to it.
MAX_AGREED_CREDIT_DAYS = 45

# How many days before the appointed day we start a courtesy reminder.
REMINDER_WINDOW_DAYS = 7


class Action(str, Enum):
    """The five bounded outcomes the engine may return."""

    GENTLE_REMINDER = "GENTLE_REMINDER"
    FIRM_REMINDER = "FIRM_REMINDER"
    ROUTE_TO_HUMAN = "ROUTE_TO_HUMAN"
    STOP_AND_ESCALATE = "STOP_AND_ESCALATE"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class Invoice:
    """The minimal invoice shape the engine needs.

    Deliberately has no `days_overdue` field — we compute the real legal clock
    from `acceptance_date`, never trust a pre-baked lateness number.
    """

    id: str
    amount: float
    acceptance_date: date  # THE CLOCK STARTS HERE, not at invoice date
    has_written_agreement: bool
    agreed_terms_days: int
    vendor_class: str  # "MICRO" | "SMALL" | "MEDIUM"
    disputed: bool
    prior_contacts: int


@dataclass(frozen=True)
class Decision:
    """The engine's output for one invoice.

    `reason` has no default: a Decision cannot be constructed without one, so
    the "every decision carries a reason" rule is enforced structurally.
    """

    invoice_id: str
    action: Action
    reason: str
    interest_owed: float
    appointed_day: date


def appointed_day(invoice: Invoice) -> date:
    """Compute the appointed day — the legal deadline after which interest runs.

    The clock starts at acceptance. With no written agreement the credit period
    is the 15-day statutory limit; with one, it is the agreed term but clamped
    to 45 days (the Act voids anything longer). The appointed day is the day
    after the due date.
    """
    credit_days = STATUTORY_CREDIT_DAYS
    if invoice.has_written_agreement:
        credit_days = invoice.agreed_terms_days
        if credit_days > MAX_AGREED_CREDIT_DAYS:
            credit_days = MAX_AGREED_CREDIT_DAYS  # clamp the overlong term
    due_date = invoice.acceptance_date + timedelta(days=credit_days)
    return due_date + timedelta(days=1)


def statutory_interest(invoice: Invoice, as_of: date) -> float:
    """MSMED Section 16 statutory interest owed as of a given date, day-accurate.

    Medium enterprises are excluded from Section 16 — returning anything but 0
    for them would be a legally false claim. Nothing accrues on or before the
    appointed day. Elapsed time is split into whole months (compounded monthly)
    plus leftover days (simple interest on the compounded balance), so a 31-day
    and a 50-day overdue invoice no longer collapse to the same "1 month".

    Worked check: principal 200000 at 3x5.50%=16.5%, 1 month + 20 days ->
      after 1 month:  200000 * 1.01375           = 202750
      leftover 20d:   202750 * (0.165/365) * 20  ~= 1833
      total interest                             ~= 4583  (vs 2750 whole-month-only)
    """
    if invoice.vendor_class == "MEDIUM":
        return 0.0  # excluded from Section 16
    ad = appointed_day(invoice)
    if as_of <= ad:
        return 0.0  # nothing accrues on or before the appointed day

    annual_rate = 3 * RBI_BANK_RATE
    monthly_rate = annual_rate / 12
    daily_rate = annual_rate / 365  # actual/365 day-count convention

    # Calendar-accurate split into whole months + leftover days (NOT 30-day
    # blocks). relativedelta clamps end-of-month correctly (Jan 31 + 1 month =
    # Feb 28/29), which a hand-rolled counter gets subtly wrong.
    delta = relativedelta(as_of, ad)
    whole_months = delta.years * 12 + delta.months
    leftover_days = delta.days

    # Step 1: compound the whole months.
    balance = invoice.amount * (1 + monthly_rate) ** whole_months
    # Step 2: simple interest on the leftover days, on the compounded balance.
    leftover_interest = balance * daily_rate * leftover_days

    total = balance + leftover_interest
    return total - invoice.amount


def decide(invoice: Invoice, now: date) -> Decision:
    """Pick one bounded action for an invoice. ORDER IS THE DESIGN.

    Compliance gates (dispute, contact cap) run first, so a disputed or capped
    invoice is structurally unreachable by any recovery branch below — it can
    never be chased by accident.
    """
    ad = appointed_day(invoice)

    # GATE 1 — never chase a disputed invoice.
    if invoice.disputed:
        return Decision(
            invoice.id,
            Action.ROUTE_TO_HUMAN,
            "Invoice disputed by buyer; removed from automated chase",
            0.0,
            ad,
        )

    # GATE 2 — respect the contact cap.
    if invoice.prior_contacts >= MAX_AUTO_CONTACTS:
        return Decision(
            invoice.id,
            Action.STOP_AND_ESCALATE,
            "Contact cap reached; escalating to human owner",
            0.0,
            ad,
        )

    # Past appointed day → interest is live → firm reminder.
    if now > ad:
        interest = statutory_interest(invoice, now)
        return Decision(
            invoice.id,
            Action.FIRM_REMINDER,
            "Past appointed day; statutory interest accruing",
            interest,
            ad,
        )

    # Within the reminder window before the appointed day → gentle nudge.
    if now > ad - timedelta(days=REMINDER_WINDOW_DAYS):
        return Decision(
            invoice.id,
            Action.GENTLE_REMINDER,
            "Approaching appointed day; courtesy reminder",
            0.0,
            ad,
        )

    # Otherwise it is too early to act.
    return Decision(
        invoice.id,
        Action.NO_ACTION,
        "Before reminder window; no action",
        0.0,
        ad,
    )
