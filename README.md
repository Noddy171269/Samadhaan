# SAMADHAAN

An autonomous decision layer for B2B invoice collection. It reads a batch of unpaid
invoices and works out the right recovery action for each one, based on who the debtor
is, what Indian law allows, and a set of hard conduct limits. Every decision it makes
is logged so a human can audit it afterwards.

Built for the Razorpay AI Buildathon, AI Revenue Recovery track.

## The problem

Micro, small and medium enterprises in India are sitting on enormous sums in overdue
B2B invoices. MSMEs make up a large share of the economy but rarely have the tools to
collect what they are owed.

The law is actually on their side. The MSMED Act, 2006 gives small suppliers real
leverage: a statutory payment deadline, compound interest that starts running
automatically once that deadline passes, and, since FY 2023 to 24, a tax penalty that
makes the *buyer* lose a deduction for paying late.

Almost nobody uses that leverage, because the tools don't know how. Existing collection
software (invoice reminders, ERP follow up levels) mostly just counts days. It sends the
same reminder to everyone based on how much time has passed. It doesn't know the
appointed day, it can't compute what is actually owed, it will happily keep chasing a
bill that is under dispute, and it has no notion of when to stop.

So the legal leverage exists, but the intelligence to use it correctly, compliantly and
at scale does not. That gap is what this project fills.

## The idea

Most collections tools treat invoices as a list to blast. This one treats each invoice
as a situation to reason about.

Here is the proof. Two invoices with the same amount and the same number of days overdue
can come out with completely different actions, because the reasoning underneath them
differs. One is MSME protected. One is disputed. One has already hit the contact cap.
The intelligence lives in telling those cases apart, not in sending anything.

Razorpay already has the sending rails: Payment Links, SMS and email reminders. What's
missing is the layer that decides what to do, to whom, when, and when to stop. That is
what this project is. It doesn't build any sending infrastructure. It decides, and hands
the action back to the rails.

## What it is not

Existing tools like Razorpay's invoice reminders and Odoo's follow up levels are day
counters with actions bolted onto thresholds: `if days_overdue > 30, send tier 3 email`.
Same cadence for everyone, no concept of the legal position, no reasoning about the
debtor, and disputes have to be excluded by hand.

| | Day counter tools (Odoo, Razorpay reminders) | SAMADHAAN |
|---|---|---|
| Trigger | days overdue against a threshold | the computed MSMED appointed day |
| Clock starts at | invoice date | acceptance date, per the Act |
| Interest | none, or a static template | live Section 16 statutory interest, day accurate |
| Disputed invoice | a human has to remember to exclude it | routed out automatically as a safety gate |
| Two identical invoices | always treated identically | differentiated by situation |

SAMADHAAN doesn't replace a sender. It sits on top of one, and supplies the reasoning
tier that Odoo and Razorpay both lack.

## Results on a batch of 55 invoices

Run `python run_batch.py` and the agent processes a reproducible synthetic batch:

```
Invoices processed    : 55
Action histogram
    GENTLE_REMINDER      8
    FIRM_REMINDER       32
    ROUTE_TO_HUMAN       6
    STOP_AND_ESCALATE    6
    NO_ACTION            3
Total statutory interest : INR 224,031.20
Actively pursued (G+F)   : 40
Escalated (cap reached)  : 6
Exceptions (disputed)    : 6
Not yet actioned         : 3
```

That INR 224,031.20 is real money quantified across the batch. Each invoice's share of
it is computed from the statute rather than pulled out of a template. Every row carries a
reason a person can read, and the whole thing is written to `report.json` for audit.

## Architecture

```
     Razorpay rails  (data in)                     Razorpay rails  (delivery out)
     Invoices / Smart Collect                         Payment Links / SMS / email
                      │                                       ▲
                      ▼                                       │
   ┌─────────────────────────────────────────────────────────────────────────────┐
   │  SAMADHAAN      the decision layer                                          │
   ├─────────────────────────────────────────────────────────────────────────────┤
   │                                                                             │
   │  1  Ingest & normalize      raw invoice data  →  clean Invoice shape        │
   │  2  Classifier (LLM)        reads the SITUATION only  →  structured JSON    │
   │  3  Decision engine         applies law + conduct  →  one bounded action    │
   │     (pure Python, no LLM)   deterministic, the brain of the system          │
   │  4  Action composer         builds reminder / route / stop                  │
   │  5  Audit log               every decision + reason  →  report.json         │
   │                                                                             │
   └─────────────────────────────────────────────────────────────────────────────┘
```

**1. Ingest and normalize** (`models.py`, `generate_data.py`). Raw invoice data is
mapped into a clean internal `Invoice` shape. In production this reads Razorpay's
Invoices API. Here it reads a reproducible synthetic batch (`invoices.json`, fixed
seed). Swapping the source changes nothing downstream.

**2. Classifier** (`classifier.py`). The only place an LLM is used. It reads the
situation, meaning urgency, customer reliability and suggested tone, and returns
structured JSON. It never picks the action.

**3. Decision engine** (`engine.py`). Pure Python, no LLM. It applies the law and the
conduct rules and picks one bounded action. Deterministic on purpose. This is the core
of the project.

**4. Action composer** (`action_composer.py`). Builds whatever the engine chose: the
reminder text, with tone shaped by the classifier, or a route to a human, or a stop.

**5. Audit log** (`audit.py`). Records every decision and its reason, computes the batch
totals, and writes the report.

## Why it's built this way

**Safety gates run first.** In the decision engine, dispute status and the contact cap
are checked before any recovery or interest logic. A disputed or capped invoice
literally cannot reach the chase logic. The zero interest on those rows isn't a
coincidence, it falls out of the structure. Recovery can never override compliance here,
because the ordering makes it impossible.

**No LLM in the control path.** The classifier interprets, the engine decides. Stopping
rules, caps and legal thresholds live in code and are never model output. There's a test
that verifies this: delete `classifier.py` and `decide()` still returns byte identical
results.

**Every decision carries a reason.** The `Decision.reason` field has no default, so you
cannot construct a decision without one. The audit requirement is enforced by the type
rather than by remembering to do it.

**Legal numbers are not invented.** Every threshold comes from the statute, set out
below. The RBI bank rate is a named constant with a comment flagging that it changes and
should be verified before use.

## Legal grounding (MSMED Act, 2006)

The clock starts at acceptance, not at the invoice date. The appointed day is the day
after the due date, and the due date is 15 days from acceptance if there is no written
agreement, or the agreed credit period if there is one. That period is capped at 45
days, because the law voids anything longer, so the engine clamps it.

Statutory interest under Section 16 is three times the RBI bank rate, compounded
monthly, running from the appointed day. It applies only to micro and small suppliers.
Medium enterprises are excluded from Section 16, so the engine returns zero interest for
them, since claiming otherwise would be legally false. The engine compounds whole months
and accrues the remaining days as simple interest, which is the conservative reading and
stays day accurate.

Then there's the 43B(h) angle. Near the end of the fiscal year, an unpaid MSME invoice
costs the buyer a tax deduction, so the agent sharpens the message for invoices that
qualify.

### Conduct rules, borrowed

India has no dedicated conduct code for B2B collections. The MSMED Act arms the supplier
but says nothing about how you're allowed to chase. So SAMADHAAN borrows the RBI Fair
Practices Code, which was written for consumer loan recovery, and treats it as a
voluntary ceiling: cap automated contacts before a human has to take over, contact only
during business hours, never chase a disputed invoice. That framework comes from the
other side of the table, and it's used here because it's the strictest standard
available.

## A note on the LLM layer

The classifier is a real Claude integration. One call per invoice, structured JSON out,
with a hard fallback if anything goes wrong.

This demo runs in fallback mode, since there's no API credit on the key, and the report
shows that state explicitly on every row. It's worth sitting with what that means. The
system is running with its AI layer entirely unavailable, and every action and every
interest figure still comes out correct, because the deterministic engine produces them.
When the LLM is available it annotates tone and urgency. It never decides anything.
Degrading safely to legally grounded behaviour is the point of the split.

## Run it

```bash
pip install -r requirements.txt
python generate_data.py      # writes invoices.json (reproducible, fixed seed)
python run_batch.py          # runs the full pipeline, prints report, writes report.json
python -m pytest             # engine + classifier tests, no network needed
```

To enable live LLM classification:

```bash
set ANTHROPIC_API_KEY=your-key-here    # Windows CMD
python run_batch.py                    # SRC column now shows real llm rows
```

## Decision outcomes

| Action | When |
|---|---|
| `GENTLE_REMINDER` | approaching the appointed day, no interest yet |
| `FIRM_REMINDER` | past the appointed day, states real interest owed plus the tax note |
| `ROUTE_TO_HUMAN` | invoice is disputed, so no pressure gets sent |
| `STOP_AND_ESCALATE` | contact cap reached, handed to a human owner |
| `NO_ACTION` | before the reminder window opens |

## How Razorpay would integrate this

The input is a clean seam. Today `load_invoices()` reads a synthetic batch. In
production it reads Razorpay's Invoices or Smart Collect API, same shape, nothing
downstream changes. The output is an action object handed back to the existing Payment
Links and SMS rails.

What this adds to Razorpay's reminder product is the one thing it doesn't have: an MSME
aware, legally grounded, auditable reasoning layer that decides what to do with each
invoice and when to stop.

*Not affiliated with or endorsed by Razorpay. Built as a buildathon submission.*
