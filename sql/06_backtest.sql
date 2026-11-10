-- BACKTEST: match as-of alerts to FDA recalls.
--
-- Alert unit: (method, product_code, firm). A month M "fires" when the method flags that firm x product code.
-- Fires at most `episode_cooldown_months` apart are merged into one alert episode (one thing for a reviewer to triage).
-- An alert is known at the END of month M. A recall is "flagged in advance" if the method fired for the same
-- firm x product code in a month whose end falls in [recall_date - lookahead, recall_date).
--
-- Population notes:
--   eligible recall  = recall_date in [backtest_start, data end]
--   detectable recall = eligible AND the firm had >= min_reports MAUDE reports for that code in the 12 months before the recall
--   precision/false alarms are computed only on MATURED alerts (alert end <= data end - lookahead), so every alert had
--   the full follow-up window to be confirmed by a recall.

-- 1) Fires from all methods --------------------------------------------------------------------
CREATE OR REPLACE TABLE fire_month AS
SELECT 'prr_sensitive' AS method, product_code, firm, M FROM signal WHERE fire_sensitive GROUP BY ALL
UNION ALL
SELECT 'prr_strict',  product_code, firm, M FROM signal WHERE fire_strict GROUP BY ALL
UNION ALL
SELECT 'prr_fdr',     product_code, firm, M FROM signal WHERE fire_fdr GROUP BY ALL
UNION ALL
SELECT 'baseline_2sd', product_code, firm, M FROM baseline_fire GROUP BY ALL
UNION ALL
SELECT 'any_activity', product_code, firm, M FROM activity_fire GROUP BY ALL;

CREATE OR REPLACE TABLE methods AS
SELECT * FROM (VALUES ('prr_sensitive'), ('prr_strict'), ('prr_fdr'), ('baseline_2sd'), ('any_activity')) t(method);

-- 2) Alert episodes ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE alert AS
WITH o AS (
    SELECT *, lag(M) OVER (PARTITION BY method, product_code, firm ORDER BY M) AS prev_m FROM fire_month
),
f AS (
    SELECT *, CASE WHEN prev_m IS NULL OR date_diff('month', prev_m, M) > param('episode_cooldown_months')::INTEGER
                   THEN 1 ELSE 0 END AS new_ep FROM o
),
e AS (
    SELECT *, sum(new_ep) OVER (PARTITION BY method, product_code, firm ORDER BY M ROWS UNBOUNDED PRECEDING) AS ep FROM f
)
SELECT method, product_code, firm, ep, min(M) AS alert_month,
       (min(M) + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE AS alert_end
FROM e GROUP BY method, product_code, firm, ep;

-- 3) Recall-level: did the method fire in advance? ------------------------------------------------
CREATE OR REPLACE TABLE recall_eval AS
WITH elig AS (
    SELECT r.*,
           EXISTS (SELECT 1 FROM rm
                   WHERE rm.product_code = r.product_code AND rm.firm = r.firm) AS firm_in_maude,
           coalesce((SELECT sum(n) FROM rm
                     WHERE rm.product_code = r.product_code AND rm.firm = r.firm
                       AND rm.m >= date_trunc('month', r.recall_date - INTERVAL 12 MONTH)
                       AND rm.m <  date_trunc('month', r.recall_date)), 0)
               >= param('min_reports')::INTEGER                               AS detectable
    FROM recall_event r
    WHERE r.recall_date >= param('backtest_start')::DATE
      AND r.recall_date <= (SELECT m + INTERVAL 1 MONTH - INTERVAL 1 DAY FROM data_end)
)
, g AS (
    SELECT m.method, e.res_event_number, e.product_code, e.area, e.firm, e.recall_date, e.firm_in_maude, e.detectable,
           min(f.M) AS first_fire_month,
           min((f.M + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE) AS first_alert_end
    FROM elig e
    CROSS JOIN methods m
    LEFT JOIN fire_month f
           ON f.method = m.method AND f.product_code = e.product_code AND f.firm = e.firm
          AND (f.M + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE <  e.recall_date
          AND (f.M + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE >= (e.recall_date - to_months(param('lookahead_months')::INTEGER))
    GROUP BY m.method, e.res_event_number, e.product_code, e.area, e.firm, e.recall_date, e.firm_in_maude, e.detectable
)
SELECT *, (recall_date - first_alert_end) / 30.4375 AS lead_months FROM g;

-- 4) Alert-level: was the alert followed by a recall? (matured alerts only) --------------------------------
CREATE OR REPLACE TABLE alert_eval AS
SELECT a.method, a.product_code, a.firm, a.alert_month, a.alert_end, sc.area,
       EXISTS (SELECT 1 FROM recall_event r
               WHERE r.product_code = a.product_code AND r.firm = a.firm
                 AND r.recall_date >  a.alert_end
                 AND r.recall_date <= a.alert_end + to_months(param('lookahead_months')::INTEGER)) AS followed_by_recall
FROM alert a
JOIN (SELECT DISTINCT product_code, area FROM scope_code) sc USING (product_code)
WHERE a.alert_end <= (SELECT (m + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE FROM data_end) - to_months(param('lookahead_months')::INTEGER);

-- 5) Evaluation table (overall and per area) --------------------------------------------------------------
CREATE OR REPLACE TABLE eval_months AS     -- months in which a matured alert could have been raised
SELECT count(*)::INTEGER AS n_months FROM (
    SELECT unnest(generate_series(param('backtest_start')::DATE,
           (SELECT m FROM data_end) - to_months(param('lookahead_months')::INTEGER), INTERVAL 1 MONTH)));

CREATE OR REPLACE TABLE eval_recall AS
SELECT method, coalesce(area, 'ALL') AS area, population,
       count(*) AS n_recalls,
       count(*) FILTER (WHERE first_fire_month IS NOT NULL) AS n_flagged_in_advance,
       round(count(*) FILTER (WHERE first_fire_month IS NOT NULL) * 1.0 / count(*), 3) AS recall_rate,
       round(median(lead_months), 1)                            AS median_lead_months,
       round(quantile_cont(lead_months, 0.25), 1)               AS lead_q1,
       round(quantile_cont(lead_months, 0.75), 1)               AS lead_q3
FROM (
    SELECT *, 'eligible' AS population FROM recall_eval
    UNION ALL
    SELECT *, 'detectable' AS population FROM recall_eval WHERE detectable
)
GROUP BY GROUPING SETS ((method, area, population), (method, population));

CREATE OR REPLACE TABLE eval_alert AS
SELECT method, coalesce(area, 'ALL') AS area,
       count(*) AS n_alerts_matured,
       count(*) FILTER (WHERE followed_by_recall) AS n_true_alerts,
       count(*) FILTER (WHERE NOT followed_by_recall) AS n_false_alerts,
       round(count(*) FILTER (WHERE followed_by_recall) * 1.0 / count(*), 3) AS precision,
       round(count(*) FILTER (WHERE NOT followed_by_recall) * 1.0 / (SELECT n_months FROM eval_months), 2) AS false_alarms_per_month
FROM alert_eval
GROUP BY GROUPING SETS ((method, area), (method));

CREATE OR REPLACE TABLE evaluation AS
SELECT r.method, r.area, r.population, r.n_recalls, r.n_flagged_in_advance, r.recall_rate,
       r.median_lead_months, r.lead_q1, r.lead_q3,
       a.n_alerts_matured, a.n_true_alerts, a.n_false_alerts, a.precision, a.false_alarms_per_month
FROM eval_recall r
LEFT JOIN eval_alert a ON a.method = r.method AND a.area = r.area
ORDER BY r.population, r.area, r.method;
