# Merchant Risk & AML Review: Findings and Recommendations

**To:** Head of Risk & Compliance · **From:** Risk Analytics · **Period:** January–June 2026
**Prepared by:** Manasvi Mittal

> Portfolio project on synthetic data. Merchants, people and the watchlist are invented, and
> bad merchants are over-sampled so each typology is visible. Thresholds are assumptions.

## Summary

The monitoring rules caught every laundering and fake-store merchant in the period, and a
settlement hold at the first alert would have stopped 94% of the ₹122 crore they processed.
The weak points are elsewhere: onboarding misses most fake stores, name-only screening floods
the team, and one monitoring rule produces most of the false positives.

| Area | Result | Main issue |
|---|---|---|
| Onboarding rating | High tier 88% bad, Low tier 1.6% | 58 of 60 fake stores rated Low or Medium |
| Sanctions / PEP screening | 6 of 6 true matches escalated | Name-only matching flags 24% of signatories |
| Transaction monitoring | 165 of 165 behavioural bad merchants caught | TM1 raises 149 false positives |
| Escalation queue | P1 100% bad, P2 67% bad | P3 (163 cases) contained no bad merchants |
| Chargebacks | 4,475 chargebacks, 48% fraud-coded | 2.4% of merchants caused 69% of fraud chargebacks |

## 1. Onboarding due diligence

| Rating | Merchants | Later confirmed bad | Bad rate |
|---|---|---|---|
| Low (0–3 points) | 2,172 | 34 | 1.6% |
| Medium (4–6) | 261 | 78 | 29.9% |
| High (7+, EDD) | 67 | 59 | 88.1% |

The rating separates risk well and keeps enhanced due diligence to 3% of merchants. It is
strong on transaction launderers (33 of 50 rated High) because their websites often do not
match the business they declare.

**Gap.** Fake stores look ordinary on paper: 58 of 60 were rated Low or Medium. Their only
strong onboarding signals are a new website and missing policy pages, worth 4 points together.

**Recommendation.** When a website is under 90 days old *and* has no refund, privacy or terms
pages, require a website review and a test purchase before go-live, or start the merchant
on a rolling reserve.

## 2. Sanctions and PEP screening

| Step | Signatories |
|---|---|
| Screened | 2,500 |
| Fuzzy name match (≥ 85) | 610 |
| Name + one identifier (analyst review) | 40 |
| Name + date of birth + nationality (escalate) | 6 |

All 6 true matches were escalated. Three were spelled differently from the list (for example
an extra letter), so **exact-name matching would have missed half of them**. Name-only fuzzy
matching would have sent 610 alerts, a quarter of all signatories, to analysts.

**Recommendation.** Keep fuzzy matching for recall, but auto-prioritise on secondary
identifiers. Close name-only hits with a recorded rationale (identifiers differ), never
silently, so the decision can be shown to an auditor.

## 3. Transaction monitoring

| Rule | Alerted | Bad | False positives | Precision | Target caught | Median days to alert |
|---|---|---|---|---|---|---|
| TM1 Turnover mismatch | 266 | 117 | 149 | 44% | 73 of 105 | 30 |
| TM2 Structuring | 60 | 55 | 5 | 92% | 55 of 55 | 34 |
| TM3 Payer concentration | 59 | 25 | 34 | 42% | 25 of 55 | 58 |
| TM4 Refunds to another instrument | 61 | 60 | 1 | 98% | 60 of 60 | 5 |
| TM5 Fraud chargeback ratio | 46 | 46 | 0 | 100% | 46 of 60 | 44 |
| TM6 Business-model mismatch | 50 | 50 | 0 | 100% | 50 of 50 | 30 |
| TM7 Account change then surge | 30 | 28 | 2 | 93% | 28 of 55 | 37 |

*Days to alert are counted from the merchant's first payment in the period.*

**Finding A: TM1 is the noise source.** Its 149 false positives are mostly genuine merchants
that under-declared turnover at onboarding. It still adds value: it is the second signal on
many laundering cases.
**Action:** treat a TM1-only alert as a request for turnover proof (GST returns, bank
statements) and a profile update, not an investigation.

**Finding B: refunds beat chargebacks for fake stores.** TM4 fired a median 5 days after a
fake store began trading; TM5 needed 44 days, because chargebacks arrive weeks after the sale.
TM5 also missed 14 fake stores that had not built up enough chargebacks yet.
**Action:** use TM4 as the trigger for a reserve; keep TM5 as confirmation.

**Finding C: a design lesson from TM6.** The first version compared each merchant's median
ticket with its category's median and caught nothing: the launderers' own payments had
dragged the category median down. The working rule uses night-time share and fixed round
amounts (wallet top-up patterns) instead.
**Lesson:** never build a peer baseline from the population being screened.

## 4. Escalation queue

| Priority | Cases | Confirmed bad | Share bad | Typical action |
|---|---|---|---|---|
| P1 urgent | 123 | 123 | 100% | Hold settlements, EDD on source of funds, consider STR to FIU-IND |
| P2 EDD | 63 | 42 | 67% | Verify the real business, rolling reserve, request evidence |
| P3 review | 163 | 0 | 0% | Turnover proof request (162 of 163 are TM1 or TM3 alone) |

349 merchants were alerted in 26 weeks, about 13 a week. Routing P3 to a lighter turnover-proof
request removes 47% of investigation work without losing a single confirmed bad merchant.

## 5. Chargebacks

- **Volume and mix:** 4,475 chargebacks: 2,144 fraud-coded (Visa 10.4, Mastercard 4837), 1,403
  consumer disputes (non-receipt, not as described) and 928 technical (duplicate processing,
  point-of-interaction errors).
- **Concentration:** 60 fake stores, 2.4% of merchants, caused 69% of fraud-coded chargebacks.
- **Disputes:** merchants represented (disputed) 1,277 chargebacks and won 708 (55%). 86 went
  to network arbitration, where the losing side also pays the network's fees.

**Recommendation.** Watch each merchant's fraud-chargeback ratio monthly against the card
networks' monitoring thresholds, and help genuine merchants represent technical chargebacks,
which are the easiest to win.

## Method and limitations

- **Approach.** Rules in SQL (DuckDB, PostgreSQL syntax); screening and scoring in Python
  (pandas, rapidfuzz). Ground-truth labels were used only to score the rules.
- **Data limits.** Synthetic patterns are cleaner than real ones. Several rules score 90–100%
  precision here and would not in production.
- **Testing limits.** The rules were tuned on the data they are scored on; they need a
  validation period on fresh data.
- **Operational assumptions.** Holding settlements at the first alert assumes legal and
  contractual grounds to do so, and STR decisions belong to the Principal Officer, not the rule.
