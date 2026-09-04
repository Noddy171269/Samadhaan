"""Synthetic invoice batch generator — DELIBERATE distribution.

This is not random noise. Each bucket is seeded so the batch visibly exercises
all five engine outcomes when run through decide(). The generator sets RAW FACTS
ONLY (dates, flags, class, amounts) — it never computes an appointed day or any
interest. That legal logic lives exclusively in engine.py.

Reference date: the batch is generated relative to REFERENCE_NOW so that outcomes
fall out of the engine, not out of hardcoded legal math. REFERENCE_NOW sits close
to the 31 Mar fiscal year-end so the 43B(h) year-end bucket is coherent — a
September 'now' would make "within ~45 days of Mar 31" impossible.

A fixed seed makes the batch reproducible: a judge re-running this gets identical
numbers.
"""

import json
import random
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from models import Invoice

# --- Reference frame (passed in from here, never hardcoded inside the model) ---
REFERENCE_NOW = date(2026, 3, 20)  # ~11 days before fiscal year-end
FISCAL_YEAR_END = date(2026, 3, 31)

SEED = 20260320
DATA_FILE = Path(__file__).with_name("invoices.json")

SUPPLIERS = [
    "Aarav Steels Pvt Ltd", "Bharat Components", "Chola Textiles",
    "Deccan Auto Parts", "Everest Packaging", "Ganga Chemicals",
    "Himalaya Tools", "Indus Electricals", "Kaveri Plastics",
    "Lotus Printing Works", "Meru Logistics Supplies", "Narmada Fabrics",
]
BUYERS = [
    "Orion Retail Ltd", "Pinnacle Motors", "Quantum Foods",
    "Radiant Appliances", "Summit Constructions", "Trident Pharma",
    "Umang Electronics", "Vega Enterprises", "Wadia Distributors",
    "Xcel Manufacturing", "Yamuna Industries", "Zenith Traders",
]
MSME_CLASSES = ["MICRO", "SMALL"]


def _rng() -> random.Random:
    return random.Random(SEED)


def _email(buyer: str) -> str:
    slug = "".join(ch for ch in buyer.lower() if ch.isalnum())
    return f"accounts@{slug}.example.com"


def _amount(rng: random.Random) -> float:
    # Realistic spread, rounded to the nearest 100 rupees.
    return float(rng.randint(100, 5000) * 100)  # 10,000 to 5,00,000


class _Factory:
    """Builds invoices with sequential ids from raw per-bucket parameters."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self._n = 0

    def make(
        self,
        *,
        acceptance_offset_days: int,
        vendor_class: str,
        has_written_agreement: bool,
        agreed_terms_days: int,
        disputed: bool,
        prior_contacts: int,
    ) -> Invoice:
        self._n += 1
        acceptance = REFERENCE_NOW - timedelta(days=acceptance_offset_days)
        # Invoice is raised a few days BEFORE goods are accepted.
        invoice_dt = acceptance - timedelta(days=self.rng.randint(2, 15))
        buyer = self.rng.choice(BUYERS)
        return Invoice(
            id=f"INV-{self._n:04d}",
            amount=_amount(self.rng),
            acceptance_date=acceptance,
            has_written_agreement=has_written_agreement,
            agreed_terms_days=agreed_terms_days,
            vendor_class=vendor_class,
            disputed=disputed,
            prior_contacts=prior_contacts,
            invoice_date=invoice_dt,
            supplier_name=self.rng.choice(SUPPLIERS),
            buyer_name=buyer,
            buyer_contact_email=_email(buyer),
            payment_status="UNPAID",
            currency="INR",
        )


def build_batch() -> list[Invoice]:
    """Assemble the 55-invoice batch, one deliberately-seeded bucket at a time.

    Date offsets are chosen so the engine lands each invoice in its intended
    outcome. Offsets, not appointed-day math — the generator stays legally dumb.
    """
    rng = _rng()
    f = _Factory(rng)
    batch: list[Invoice] = []

    # 20 — clean overdue MSME, not disputed, chased 0-2 times, well past the
    # appointed day (offset >= 60 clears even a 45-day agreed term) → FIRM_REMINDER.
    for _ in range(20):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(60, 150),
                vendor_class=rng.choice(MSME_CLASSES),
                has_written_agreement=rng.random() < 0.5,
                agreed_terms_days=rng.choice([30, 45]),
                disputed=False,
                prior_contacts=rng.randint(0, 2),
            )
        )

    # 8 — approaching the appointed day (15-day clock, appointed lands 2-6 days
    # ahead of now) → GENTLE_REMINDER. Force no-agreement for a deterministic clock.
    for _ in range(8):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(10, 14),
                vendor_class=rng.choice(MSME_CLASSES),
                has_written_agreement=False,
                agreed_terms_days=0,
                disputed=False,
                prior_contacts=rng.randint(0, 2),
            )
        )

    # 6 — disputed (otherwise chaseable) → ROUTE_TO_HUMAN, regardless of dates.
    for _ in range(6):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(60, 150),
                vendor_class=rng.choice(MSME_CLASSES),
                has_written_agreement=rng.random() < 0.5,
                agreed_terms_days=rng.choice([30, 45]),
                disputed=True,
                prior_contacts=rng.randint(0, 2),
            )
        )

    # 6 — contact cap reached (prior_contacts >= 3), not disputed → STOP_AND_ESCALATE.
    for _ in range(6):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(60, 150),
                vendor_class=rng.choice(MSME_CLASSES),
                has_written_agreement=rng.random() < 0.5,
                agreed_terms_days=rng.choice([30, 45]),
                disputed=False,
                prior_contacts=rng.randint(3, 5),
            )
        )

    # 5 — MEDIUM vendor, overdue → FIRM_REMINDER but interest MUST be 0
    # (Section 16 excludes medium enterprises). The correctness proof.
    for _ in range(5):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(60, 150),
                vendor_class="MEDIUM",
                has_written_agreement=rng.random() < 0.5,
                agreed_terms_days=rng.choice([30, 45]),
                disputed=False,
                prior_contacts=rng.randint(0, 2),
            )
        )

    # 5 — no written agreement (15-day statutory clock), overdue → FIRM_REMINDER,
    # with an earlier appointed day than the agreement-based cases.
    for _ in range(5):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(40, 120),
                vendor_class=rng.choice(MSME_CLASSES),
                has_written_agreement=False,
                agreed_terms_days=0,
                disputed=False,
                prior_contacts=rng.randint(0, 2),
            )
        )

    # 3 — recently accepted, before the reminder window → NO_ACTION.
    for _ in range(3):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(2, 7),
                vendor_class=rng.choice(MSME_CLASSES),
                has_written_agreement=False,
                agreed_terms_days=0,
                disputed=False,
                prior_contacts=0,
            )
        )

    # 2 — near fiscal year-end: accepted ~50-65 days back so they are unpaid and
    # overdue right at 31 Mar → FIRM_REMINDER, and flaggable for the 43B(h) tax
    # angle by a later stage. (Offset from REFERENCE_NOW lands acceptance in Jan.)
    for _ in range(2):
        batch.append(
            f.make(
                acceptance_offset_days=rng.randint(50, 65),
                vendor_class=rng.choice(MSME_CLASSES),
                has_written_agreement=False,
                agreed_terms_days=0,
                disputed=False,
                prior_contacts=rng.randint(0, 2),
            )
        )

    return batch


# --- Serialization -----------------------------------------------------------

def _to_dict(inv: Invoice) -> dict:
    d = asdict(inv)
    d["acceptance_date"] = inv.acceptance_date.isoformat()
    d["invoice_date"] = inv.invoice_date.isoformat()
    return d


def _from_dict(d: dict) -> Invoice:
    d = dict(d)
    d["acceptance_date"] = date.fromisoformat(d["acceptance_date"])
    d["invoice_date"] = date.fromisoformat(d["invoice_date"])
    return Invoice(**d)


def save_invoices(batch: list[Invoice], path: Path = DATA_FILE) -> None:
    path.write_text(
        json.dumps([_to_dict(i) for i in batch], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_invoices(path: Path = DATA_FILE) -> list[Invoice]:
    """Read the batch back as a list[Invoice] — the shared input for every stage."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_from_dict(d) for d in raw]


if __name__ == "__main__":
    batch = build_batch()
    save_invoices(batch)
    print(f"Wrote {len(batch)} invoices to {DATA_FILE.name} (seed={SEED}, now={REFERENCE_NOW}).")
