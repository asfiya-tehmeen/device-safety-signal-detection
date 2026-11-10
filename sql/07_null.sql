-- NULL TEST: do the alerts carry timing information, or do big firms simply fire all the time?
--
-- For each recall (same firm, same product code) the recall date is replaced by a pseudo-random date, 200 times.
-- If a method "flags in advance" about as many random dates as real recall dates, its hits come from firms being
-- flagged constantly, not from warning before recalls.
--
-- Like-for-like population: recall dates (real and random) from backtest_start + lookahead onwards, so every date
-- has a full look-back window inside the period where signals exist.
-- Random dates come from a hash, so the result is identical on every rebuild.

CREATE OR REPLACE TABLE null_bounds AS
SELECT (param('backtest_start')::DATE + to_months(param('lookahead_months')::INTEGER))::DATE AS lo,
       (SELECT (m + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE FROM data_end)                  AS hi;

CREATE OR REPLACE TABLE null_reps AS SELECT unnest(range(1, 201))::INTEGER AS rep;

CREATE OR REPLACE TABLE null_recall AS
WITH base AS (
    SELECT DISTINCT res_event_number, product_code, firm
    FROM recall_eval
    WHERE recall_date >= (SELECT lo FROM null_bounds)
),
dated AS (
    SELECT b.*, s.rep,
           (nb.lo + (hash(b.res_event_number, b.product_code, b.firm, s.rep) % ((nb.hi - nb.lo) + 1))::INTEGER)::DATE AS fake_date
    FROM base b CROSS JOIN null_reps s CROSS JOIN null_bounds nb
)
SELECT m.method, d.rep, d.res_event_number, d.product_code, d.firm, d.fake_date,
       EXISTS (SELECT 1 FROM fire_month f
               WHERE f.method = m.method AND f.product_code = d.product_code AND f.firm = d.firm
                 AND (f.M + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE <  d.fake_date
                 AND (f.M + INTERVAL 1 MONTH - INTERVAL 1 DAY)::DATE >= d.fake_date - to_months(param('lookahead_months')::INTEGER)
       ) AS hit
FROM dated d CROSS JOIN methods m;

CREATE OR REPLACE TABLE null_summary AS
WITH obs AS (
    SELECT method, count(*) AS n_recalls, avg((first_fire_month IS NOT NULL)::INTEGER) AS observed_rate
    FROM recall_eval
    WHERE recall_date >= (SELECT lo FROM null_bounds)
    GROUP BY method
),
reps AS (
    SELECT method, rep, avg(hit::INTEGER) AS rate FROM null_recall GROUP BY method, rep
)
SELECT o.method, o.n_recalls,
       round(o.observed_rate, 3)                                        AS observed_rate,
       round(avg(r.rate), 3)                                            AS null_mean_rate,
       round(quantile_cont(r.rate, 0.025), 3)                           AS null_p2_5,
       round(quantile_cont(r.rate, 0.975), 3)                           AS null_p97_5,
       round(o.observed_rate - avg(r.rate), 3)                          AS lift_over_random,
       round((count(*) FILTER (WHERE r.rate >= o.observed_rate) + 1) * 1.0 / (count(*) + 1), 4) AS p_value
FROM obs o JOIN reps r USING (method)
GROUP BY o.method, o.n_recalls, o.observed_rate
ORDER BY o.method;
