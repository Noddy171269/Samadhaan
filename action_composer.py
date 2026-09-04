"""Action composer — turns each engine Decision into a concrete output.

The composer READS the classifier's suggested_tone to shape wording and reads
the decision's action + interest to fill the template. It NEVER changes the action
and never recomputes interest. Wording is pure f-string templating — there is no
second LLM call here. If a message is produced it is for the rails to send; the
composer just writes it.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from engine import Action

# 43B(h) covers amounts payable to MICRO and SMALL enterprises (not MEDIUM).
_MSME_43BH = {"MICRO", "SMALL"}
# How close to the 31 Mar fiscal year-end the reporting date must be for the
# tax-disallowance exposure to be worth flagging.
YEAR_END_WINDOW_DAYS = 45

_YEAR_END_NOTE = (
    " Please note: as this amount remains unpaid at the close of the financial "
    "year (31 March), it may be disallowed as a deduction to your business under "
    "Section 43B(h) of the Income-tax Act, 1961."
)


@dataclass(frozen=True)
class ActionOutput:
    invoice_id: str
    action: Action  # copied straight from the engine — never altered here
    message: Optional[str]  # text to send, or None for non-message actions
    channel: str  # "email" | "none"
    reason: str  # copied from decision.reason (audit trail)


def _days_to_year_end(now: date) -> int:
    """Days from `now` to the next 31 Mar fiscal year-end."""
    fy_end = date(now.year, 3, 31)
    if now > fy_end:
        fy_end = date(now.year + 1, 3, 31)
    return (fy_end - now).days


def is_year_end_candidate(invoice, now: date) -> bool:
    """True when an unpaid micro/small invoice sits inside the year-end window.

    This is the real 43B(h) condition — proximity of the *reporting date* to
    31 Mar, not the invoice's acceptance date — so it is time-relative and needs
    `now` passed in.
    """
    return (
        invoice.vendor_class in _MSME_43BH
        and invoice.payment_status != "PAID"
        and 0 <= _days_to_year_end(now) <= YEAR_END_WINDOW_DAYS
    )


def _inr(amount: float) -> str:
    return f"₹{amount:,.2f}"


def _gentle_message(invoice, tone: str) -> str:
    buyer, ref, amt = invoice.buyer_name, invoice.id, _inr(invoice.amount)
    if tone == "friendly":
        return (
            f"Hi {buyer}, just a friendly reminder that invoice {ref} for {amt} "
            f"is coming due. We'd appreciate settling it at your convenience."
        )
    if tone == "formal":
        return (
            f"Dear {buyer}, we wish to remind you that invoice {ref} for {amt} "
            f"is due shortly. Kindly ensure timely settlement."
        )
    # firm (default)
    return (
        f"Dear {buyer}, this is a reminder that invoice {ref} for {amt} is "
        f"approaching its due date. Please arrange payment on time."
    )


def _firm_message(invoice, tone: str, interest: float, year_end: bool) -> str:
    buyer, ref, amt, owed = invoice.buyer_name, invoice.id, _inr(invoice.amount), _inr(interest)
    if tone == "friendly":
        base = (
            f"Hi {buyer}, invoice {ref} for {amt} is now past its due date. "
            f"Statutory interest of {owed} has begun to accrue under the MSMED "
            f"Act, 2006. Please settle the amount at the earliest."
        )
    elif tone == "formal":
        base = (
            f"Dear {buyer}, invoice {ref} ({amt}) remains unpaid beyond the "
            f"appointed day. Statutory interest of {owed} is due under Section 16 "
            f"of the MSMED Act, 2006. Kindly remit the outstanding amount without "
            f"further delay."
        )
    else:  # firm (default)
        base = (
            f"Dear {buyer}, invoice {ref} for {amt} is overdue. Statutory interest "
            f"of {owed} is now payable under Section 16 of the MSMED Act, 2006. "
            f"We request immediate payment."
        )
    return base + (_YEAR_END_NOTE if year_end else "")


def compose(invoice, classification, decision, now: date) -> ActionOutput:
    """Build the concrete output for one decided invoice.

    Reads classification.suggested_tone for wording only; the action and interest
    come from the engine and are passed through unchanged.
    """
    action = decision.action
    tone = classification.suggested_tone

    if action == Action.GENTLE_REMINDER:
        message = _gentle_message(invoice, tone)
        channel = "email"
    elif action == Action.FIRM_REMINDER:
        message = _firm_message(
            invoice, tone, decision.interest_owed, is_year_end_candidate(invoice, now)
        )
        channel = "email"
    else:
        # ROUTE_TO_HUMAN / STOP_AND_ESCALATE / NO_ACTION — no message is sent.
        message = None
        channel = "none"

    return ActionOutput(
        invoice_id=invoice.id,
        action=action,
        message=message,
        channel=channel,
        reason=decision.reason,
    )
