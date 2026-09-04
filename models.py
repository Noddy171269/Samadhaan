"""The full Invoice model.

The decision engine (engine.py) reads only 8 of these fields. The rest make the
data realistic and feed later stages (classifier, action composer, audit log).
Deliberately NO legal logic lives here — the model holds raw facts; the engine
computes the appointed day and interest. `days_since_acceptance` is a readability
helper, not a legal calculation.
"""

from dataclasses import dataclass
from datetime import date


@dataclass
class Invoice:
    # --- Engine-critical fields (read by decide()) ---
    id: str
    amount: float
    acceptance_date: date  # clock start — NOT invoice date
    has_written_agreement: bool
    agreed_terms_days: int
    vendor_class: str  # "MICRO" | "SMALL" | "MEDIUM"
    disputed: bool
    prior_contacts: int

    # --- Realism / downstream fields (not read by the engine) ---
    invoice_date: date  # when the invoice was raised (before acceptance)
    supplier_name: str
    buyer_name: str
    buyer_contact_email: str
    payment_status: str = "UNPAID"  # "UNPAID" | "PARTIAL" | "PAID"
    currency: str = "INR"

    def days_since_acceptance(self, as_of: date) -> int:
        """How many days have passed since acceptance, as of a reference date.

        Pure readability helper. The legal clock (appointed day, interest) is the
        engine's job — do not reproduce it here.
        """
        return (as_of - self.acceptance_date).days
