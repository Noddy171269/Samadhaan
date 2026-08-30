# Receivables Agent — Project Brief

## What this is
An autonomous **decision layer** for B2B invoice collection, built for the Razorpay
AI Buildathon (AI Revenue Recovery track). It reads a batch of unpaid invoices and,
for each one, decides the right recovery action — grounded in who the debtor is,
what Indian law says, and hard conduct limits — then logs every decision so a human
can audit it.

**It is a brain, not a mouth.** Razorpay already has the sending rails (Payment Links,
SMS/email reminders). What they lack is the reasoning layer that decides *what* to do,
*to whom*, *when*, and *when to stop*. That reasoning layer is this project. Do not
build sending infrastructure — the agent decides and hands an action back to the rails.

## Language
Python. Chosen for iteration speed and clean LLM integration. The deterministic
decision engine is the piece that would be rewritten in Go for production scale —
but for this build, Python is the right tool.

## The core idea (do not lose this)
Every competitor's tool treats invoices as a list to blast. This one treats each
invoice as a **situation to reason about**. The proof is that two invoices with
identical amount and days-overdue can get completely different actions because the
reasoning underneath differs (one is MSME-protected, one is disputed, one has hit
the contact cap). The intelligence is in *differentiating*, not in *sending*.

## Architecture — five stages
1. **Ingest & normalize** — map raw invoice data into a clean internal `Invoice` shape.
2. **Classifier (LLM)** — the ONLY place an LLM is used. It reads the *situation*
   (urgency, customer reliability, suggested tone) and returns structured JSON.
   It NEVER decides the action.
3. **Decision engine (pure Python, no LLM)** — applies the law and the conduct rules
   to pick a bounded action. This is the brain. Deterministic on purpose.
4. **Action composer** — builds the chosen action (reminder text, route-to-human, stop).
5. **Audit log** — records every decision + reason, computes recovered/escalated/
   exception totals, produces the batch report (the actual deliverable).

## Non-negotiable design rules
- **Safety gates run FIRST.** In the decision engine, check dispute status and the
  contact cap BEFORE any recovery/interest logic. Recovery must never override
  compliance. This ordering is deliberate and is the whole point — do not reorder it.
- **No LLM in the control path.** The classifier interprets; the engine decides.
  Keep that separation clean. Stopping rules, caps, and legal thresholds are code,
  never model output.
- **Every decision carries a human-readable `reason` string.** This feeds the audit
  log. A decision without a reason is a bug.
- **Do not invent legal numbers.** The thresholds below come from the actual statute.

## The legal logic (MSMED Act 2006)
- The clock does NOT start at invoice date. It starts at `acceptance_date`.
- **Appointed day** = due date + 1, where due date is:
  - 15 days from acceptance if there is NO written agreement, OR
  - the agreed credit period if there IS one — but capped at 45 days (the law voids
    anything longer, so clamp it).
- **Statutory interest** (Section 16): 3× the RBI bank rate, compounded monthly,
  running from the appointed day. Bank rate is a NAMED CONSTANT (currently ~5.50%,
  must be verifiable/updatable — it changes). Interest applies ONLY to micro/small
  suppliers, NEVER medium (they're excluded from Section 16 — claiming otherwise is
  legally false).
- **43B(h) tax angle**: near fiscal year-end (Mar 31), an unpaid MSME invoice costs
  the buyer a tax deduction. Use this to sharpen the message near year-end.

## The conduct logic (borrowed, and say so)
There is NO dedicated B2B collections conduct code in India. The MSMED Act arms the
supplier but is silent on how you chase. So we borrow the RBI Fair Practices Code
(written for consumer-loan recovery) as a VOLUNTARY ethical ceiling:
- Cap automated contacts (default: 3) before mandatory human escalation.
- Only contact during business hours.
- Never chase a disputed invoice — route it to a human instead.
Be honest in the writeup that this is borrowed from a different side of the table.

## Decision outcomes (the Action enum)
- `GENTLE_REMINDER` — approaching appointed day, no interest yet.
- `FIRM_REMINDER` — past appointed day, states real interest owed + tax note.
- `ROUTE_TO_HUMAN` — invoice disputed; no pressure sent.
- `STOP_AND_ESCALATE` — contact cap reached; hand to human owner.
- `NO_ACTION` — before the reminder window.

## How to work on this
- Build ONE stage at a time. Write the file, write a test, run it, review, commit.
- Start with the decision engine (stage 3) — it's the core. Feed it three example
  invoices (clean+overdue, disputed, cap-reached) and confirm three different outcomes.
- Explain WHY before writing non-obvious logic. The author must be able to defend
  every design choice in a 5-minute video — no unexplained auto-generated code.
- Commit after each working stage. The deliverable is repo + video + architecture.
