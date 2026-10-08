-- =====================================================================================
-- Transaction-monitoring (AML / merchant fraud) rules for a payment aggregator
-- Dialect: DuckDB (PostgreSQL-compatible window functions and INTERVAL syntax)
--
-- Every rule returns: rule_id, merchant_id, alert_ts, reason
-- `reason` is a plain-language sentence an analyst can paste into the case file, so every
-- alert is explainable to the merchant, to auditors and to the regulator.
-- Thresholds are stated assumptions for this exercise, not regulatory values.
-- =====================================================================================


-- TM1  TURNOVER MISMATCH  (laundering, under-declared business)
-- Month-to-date volume passes 3x the turnover the merchant declared at onboarding.
CREATE OR REPLACE VIEW tm1_turnover_mismatch AS
WITH w AS (
    SELECT t.merchant_id, t.ts, m.declared_monthly_turnover AS declared,
           SUM(t.amount) OVER (PARTITION BY t.merchant_id, date_trunc('month', t.ts) ORDER BY t.ts
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS mtd
    FROM transactions t JOIN merchants m USING (merchant_id)
)
SELECT 'TM1_turnover_mismatch' AS rule_id, merchant_id, MIN(ts) AS alert_ts,
       'Month-to-date volume of Rs ' || CAST(ROUND(MIN(mtd) / 1e5, 1) AS VARCHAR)
       || ' lakh exceeded 3x the declared monthly turnover of Rs '
       || CAST(ROUND(ANY_VALUE(declared) / 1e5, 1) AS VARCHAR) || ' lakh' AS reason
FROM w
WHERE mtd > 3 * declared
GROUP BY merchant_id, date_trunc('month', ts);


-- TM2  STRUCTURING  (laundering)
-- 5+ payments between Rs 45,000 and Rs 49,999 within 7 days: amounts kept just under an
-- assumed Rs 50,000 enhanced-check threshold.
CREATE OR REPLACE VIEW tm2_structuring AS
WITH s AS (
    SELECT merchant_id, ts,
           COUNT(*) OVER (PARTITION BY merchant_id ORDER BY ts
                          RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND CURRENT ROW) AS n_7d
    FROM transactions
    WHERE amount BETWEEN 45000 AND 49999.99
)
SELECT 'TM2_structuring' AS rule_id, merchant_id, MIN(ts) AS alert_ts,
       CAST(MAX(n_7d) AS VARCHAR) || ' payments between Rs 45,000 and Rs 49,999 within 7 days' AS reason
FROM s
WHERE n_7d >= 5
GROUP BY merchant_id;


-- TM3  PAYER CONCENTRATION  (laundering via a few funders)
-- A month with Rs 10 lakh+ of volume where the top 5 payers sent 70%+ of it.
CREATE OR REPLACE VIEW tm3_payer_concentration AS
WITH pm AS (
    SELECT merchant_id, date_trunc('month', ts) AS month, payer_id,
           SUM(amount) AS amt, MAX(ts) AS last_ts
    FROM transactions GROUP BY ALL
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY merchant_id, month ORDER BY amt DESC) AS rk,
              SUM(amt) OVER (PARTITION BY merchant_id, month) AS month_total,
              MAX(last_ts) OVER (PARTITION BY merchant_id, month) AS month_last_ts
    FROM pm
)
SELECT 'TM3_payer_concentration' AS rule_id, merchant_id, MIN(month_last_ts) AS alert_ts,
       'Top 5 payers sent ' || CAST(ROUND(100 * MAX(top5 / month_total)) AS VARCHAR)
       || '% of a Rs ' || CAST(ROUND(MAX(month_total) / 1e5, 1) AS VARCHAR) || ' lakh month' AS reason
FROM (
    SELECT merchant_id, month, month_total, month_last_ts, SUM(amt) AS top5
    FROM ranked WHERE rk <= 5 GROUP BY ALL
)
WHERE month_total >= 1000000 AND top5 >= 0.7 * month_total
GROUP BY merchant_id;


-- TM4  REFUNDS TO A DIFFERENT INSTRUMENT  (fake store, cash-out)
-- 3+ refunds in 30 days paid to an instrument other than the one that paid.
CREATE OR REPLACE VIEW tm4_refund_other_instrument AS
WITH r AS (
    SELECT merchant_id, refund_ts,
           COUNT(*) OVER (PARTITION BY merchant_id ORDER BY refund_ts
                          RANGE BETWEEN INTERVAL 30 DAY PRECEDING AND CURRENT ROW) AS n_30d
    FROM refunds
    WHERE NOT to_original_instrument
)
SELECT 'TM4_refund_other_instrument' AS rule_id, merchant_id, MIN(refund_ts) AS alert_ts,
       CAST(MAX(n_30d) AS VARCHAR) || ' refunds in 30 days sent to an instrument other than the paying one' AS reason
FROM r
WHERE n_30d >= 3
GROUP BY merchant_id;


-- TM5  FRAUD CHARGEBACK RATIO  (fake store, compromised merchant)
-- In a calendar month: 5+ fraud-coded chargebacks (Visa 10.4 / Mastercard 4837) AND
-- fraud chargebacks above 1% of card transactions (assumption modelled on card-network
-- monitoring programmes).
CREATE OR REPLACE VIEW tm5_fraud_chargeback_ratio AS
WITH cb AS (
    SELECT merchant_id, date_trunc('month', cb_date) AS month, COUNT(*) AS n_fraud_cb, MAX(cb_date) AS last_cb
    FROM chargebacks WHERE reason_group = 'fraud' GROUP BY ALL
), card AS (
    SELECT merchant_id, date_trunc('month', ts) AS month, COUNT(*) AS n_card
    FROM transactions WHERE method = 'card' GROUP BY ALL
)
SELECT 'TM5_fraud_chargeback_ratio' AS rule_id, cb.merchant_id, MIN(cb.last_cb) AS alert_ts,
       'Fraud chargebacks were ' || CAST(ROUND(100.0 * MAX(cb.n_fraud_cb / card.n_card), 1) AS VARCHAR)
       || '% of card transactions in a month (' || CAST(MAX(cb.n_fraud_cb) AS VARCHAR) || ' chargebacks)' AS reason
FROM cb JOIN card USING (merchant_id, month)
WHERE cb.n_fraud_cb >= 5 AND cb.n_fraud_cb > 0.01 * card.n_card
GROUP BY cb.merchant_id;


-- TM6  BUSINESS-MODEL MISMATCH  (transaction laundering)
-- A month with 200+ payments where 50%+ arrive between 22:00 and 04:00 AND 80%+ are fixed
-- round amounts (Rs 100, 500, 1,000 ...), the pattern of wallet top-ups for betting or
-- gaming, not of the education / consulting / digital-goods business declared.
-- Design note: a first version compared each merchant's median ticket with its category's
-- median and caught nothing, because the launderers' own volume dragged the category median
-- down. Peer baselines must not be built from the population being screened.
CREATE OR REPLACE VIEW tm6_business_model_mismatch AS
WITH mm AS (
    SELECT t.merchant_id, m.category, date_trunc('month', t.ts) AS month, COUNT(*) AS n,
           AVG(CASE WHEN hour(t.ts) >= 22 OR hour(t.ts) < 4 THEN 1 ELSE 0 END) AS night_share,
           AVG(CASE WHEN t.amount % 50 = 0 THEN 1 ELSE 0 END) AS round_share,
           MAX(t.ts) AS last_ts
    FROM transactions t JOIN merchants m USING (merchant_id) GROUP BY ALL
)
SELECT 'TM6_business_model_mismatch' AS rule_id, merchant_id, MIN(last_ts) AS alert_ts,
       CAST(ROUND(100 * MAX(night_share)) AS VARCHAR) || '% of payments at night and '
       || CAST(ROUND(100 * MAX(round_share)) AS VARCHAR) || '% fixed round amounts, unusual for a '
       || ANY_VALUE(category) || ' merchant' AS reason
FROM mm
WHERE n >= 200 AND night_share >= 0.5 AND round_share >= 0.8
GROUP BY merchant_id;


-- TM7  SETTLEMENT ACCOUNT CHANGE THEN SURGE  (mule account, account takeover)
-- Volume in the 30 days after a settlement bank-account change exceeds 1.5x declared
-- monthly turnover.
CREATE OR REPLACE VIEW tm7_account_change_surge AS
WITH chg AS (
    SELECT merchant_id, event_date FROM merchant_events WHERE event_type = 'settlement_account_change'
), w AS (
    SELECT c.merchant_id, c.event_date, m.declared_monthly_turnover AS declared, t.ts,
           SUM(t.amount) OVER (PARTITION BY c.merchant_id, c.event_date ORDER BY t.ts
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum
    FROM chg c
    JOIN merchants m USING (merchant_id)
    JOIN transactions t ON t.merchant_id = c.merchant_id
                        AND t.ts >= c.event_date AND t.ts < c.event_date + INTERVAL 30 DAY
)
SELECT 'TM7_account_change_surge' AS rule_id, merchant_id, MIN(ts) AS alert_ts,
       'Settlement bank account changed, then Rs ' || CAST(ROUND(MAX(cum) / 1e5, 1) AS VARCHAR)
       || ' lakh processed within 30 days (1.5x+ declared monthly turnover)' AS reason
FROM w
WHERE cum > 1.5 * declared
GROUP BY merchant_id;
