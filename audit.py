"""Audit report — the actual deliverable.

Collects every (invoice, classification, decision, action) into per-invoice rows,
computes the batch totals a judge cares about, prints a clean terminal table (the
video demo), and writes report.json (the inspectable artifact). This is where the
"a human can audit every decision" promise is kept: every row carries its reason.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from engine import Action

REPORT_FILE = Path(__file__).with_name("report.json")


@dataclass
class _Row:
    invoice_id: str
    action: str
    interest_owed: float
    classification_source: str  # "llm" | "fallback"
    channel: str
    reason: str


@dataclass
class Audit:
    rows: list = field(default_factory=list)

    def record(self, invoice, classification, decision, action_output) -> None:
        # Store the raw interest; round only for display/JSON so the batch total
        # matches the engine's exact figure (per-row rounding would drift it).
        self.rows.append(
            _Row(
                invoice_id=invoice.id,
                action=decision.action.value,
                interest_owed=decision.interest_owed,
                classification_source=classification.source,
                channel=action_output.channel,
                reason=decision.reason,
            )
        )

    def summary(self) -> dict:
        counts = Counter(r.action for r in self.rows)
        total_interest = round(sum(r.interest_owed for r in self.rows), 2)
        llm = sum(1 for r in self.rows if r.classification_source == "llm")
        fallback = sum(1 for r in self.rows if r.classification_source == "fallback")
        return {
            "total_invoices": len(self.rows),
            "action_histogram": {a.value: counts.get(a.value, 0) for a in Action},
            "total_statutory_interest": total_interest,
            "recovered_track": counts.get(Action.GENTLE_REMINDER.value, 0)
            + counts.get(Action.FIRM_REMINDER.value, 0),
            "escalated": counts.get(Action.STOP_AND_ESCALATE.value, 0),
            "exceptions": counts.get(Action.ROUTE_TO_HUMAN.value, 0),
            "no_action": counts.get(Action.NO_ACTION.value, 0),
            "llm_classified": llm,
            "fallback_classified": fallback,
        }

    def print_report(self) -> None:
        s = self.summary()
        print("=" * 78)
        print("  SAMADHAAN - Receivables Agent : Batch Decision Report")
        print("=" * 78)
        print(f"  {'ID':<10}{'ACTION':<18}{'INTEREST':>13}  {'SRC':<9}REASON")
        print("  " + "-" * 74)
        for r in self.rows:
            reason = r.reason if len(r.reason) <= 34 else r.reason[:31] + "..."
            print(
                f"  {r.invoice_id:<10}{r.action:<18}{r.interest_owed:>13,.2f}  "
                f"{r.classification_source:<9}{reason}"
            )
        print("  " + "-" * 74)
        print(f"\n  Invoices processed        : {s['total_invoices']}")
        print("  Action histogram")
        for action, n in s["action_histogram"].items():
            print(f"      {action:<18} {n:>3}")
        print(f"  Total statutory interest  : INR {s['total_statutory_interest']:,.2f}")
        print(f"  Actively pursued (G+F)    : {s['recovered_track']}")
        print(f"  Escalated (cap reached)   : {s['escalated']}")
        print(f"  Exceptions (disputed)     : {s['exceptions']}")
        print(f"  Not yet actioned          : {s['no_action']}")
        print(
            f"  LLM coverage              : {s['llm_classified']} classified by LLM, "
            f"{s['fallback_classified']} fell back"
        )
        print("=" * 78)

    def write_json(self, path: Path = REPORT_FILE) -> None:
        def row_dict(r):
            d = dict(r.__dict__)
            d["interest_owed"] = round(r.interest_owed, 2)  # round for the artifact only
            return d

        payload = {
            "summary": self.summary(),
            "invoices": [row_dict(r) for r in self.rows],
        }
        Path(path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
