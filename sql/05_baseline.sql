-- BASELINE rule the signals must beat (as-of by construction: uses only the 12 months BEFORE month M):
--   flag firm x product code in month M when its report count n >= min_reports
--   and n > mean(previous 12 months) + k * sd(previous 12 months), k = baseline_sd (default 2).
-- Counts are on a dense month spine, so months with zero reports count as zero.

CREATE OR REPLACE TABLE spine AS
SELECT f.product_code, f.firm, m.m
FROM (SELECT DISTINCT product_code, firm FROM rm) f
CROSS JOIN (
    SELECT unnest(generate_series(date_trunc('month', param('start_date')::DATE)::DATE,
                                  (SELECT m FROM data_end), INTERVAL 1 MONTH))::DATE AS m
) m;

CREATE OR REPLACE TABLE firm_month AS
SELECT s.product_code, s.firm, s.m, coalesce(r.n, 0) AS n
FROM spine s LEFT JOIN rm r USING (product_code, firm, m);

CREATE OR REPLACE TABLE baseline_stats AS
SELECT *,
       avg(n)         OVER w AS mean12,
       stddev_samp(n) OVER w AS sd12,
       count(*)       OVER w AS hist
FROM firm_month
WINDOW w AS (PARTITION BY product_code, firm ORDER BY m ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING);

CREATE OR REPLACE TABLE baseline_fire AS
SELECT product_code, firm, m AS M, n, mean12, sd12
FROM baseline_stats
WHERE hist = 12
  AND m >= param('backtest_start')::DATE
  AND n >= param('min_reports')::INTEGER
  AND n > mean12 + param('baseline_sd')::DOUBLE * coalesce(sd12, 0);

-- Upper-bound reference rule ("always on"): flag every firm x product code month with >= min_reports reports.
-- It shows how much of any method's recall rate comes simply from big firms being active all the time.
CREATE OR REPLACE TABLE activity_fire AS
SELECT product_code, firm, m AS M, n
FROM firm_month
WHERE m >= param('backtest_start')::DATE
  AND n >= param('min_reports')::INTEGER;
