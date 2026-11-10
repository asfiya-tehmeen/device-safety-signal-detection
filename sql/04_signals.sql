-- SIGNAL layer: as-of disproportionality (PRR, ROR with 95% CI) + trend flag, for every month M.
--
-- As-of rule: the row for month M uses ONLY reports with date_received <= end of M.
-- Every window below ends at M and looks backwards; nothing after M is ever read.
-- tests/test_signals.py proves this by recomputing on data truncated at M and comparing.
--
-- Unit of analysis: (product_code, firm, problem term). Comparator: all OTHER firms in the same product code.
-- Window: trailing 12 months ending at M.
--   a = reports of this firm with this problem        b = this firm's other reports
--   c = other firms' reports with this problem        d = other firms' other reports
-- Trend: reports with this pair in the last 3 months (k3) vs Poisson expectation from the
--        12 months before that (base12), expected = (base12 + 0.5) * 3 / 12.

CREATE OR REPLACE TABLE data_end AS
SELECT date_trunc('month', max(date_received))::DATE AS m FROM event;

-- Monthly building blocks ---------------------------------------------------------------
CREATE OR REPLACE TABLE rm AS            -- reports per product code x firm x month
SELECT product_code, firm, date_trunc('month', date_received)::DATE AS m, count(*) AS n
FROM event GROUP BY ALL;

CREATE OR REPLACE TABLE pm AS            -- reports per product code x firm x problem x month
SELECT e.product_code, e.firm, p.problem, date_trunc('month', e.date_received)::DATE AS m, count(*) AS n
FROM event e
JOIN event_problem p ON p.report_key = e.report_key AND p.product_code = e.product_code
WHERE p.problem NOT IN (SELECT problem FROM problem_generic)
GROUP BY ALL;

CREATE OR REPLACE TABLE offs AS SELECT unnest(range(0, 15))::INTEGER AS off;

-- Expand each monthly count into every as-of month M (m .. m+14) whose windows contain it.
CREATE OR REPLACE TABLE pm_win AS
SELECT pm.product_code, pm.firm, pm.problem, (pm.m + to_months(o.off))::DATE AS M,
       sum(n) FILTER (WHERE o.off <= 11)  AS a12,
       coalesce(sum(n) FILTER (WHERE o.off <= 2), 0)  AS k3,
       coalesce(sum(n) FILTER (WHERE o.off >= 3), 0)  AS base12
FROM pm CROSS JOIN offs o
WHERE (pm.m + to_months(o.off))::DATE <= (SELECT m FROM data_end)
GROUP BY ALL;

CREATE OR REPLACE TABLE firm_win AS      -- a+b: all reports of the firm in the window
SELECT rm.product_code, rm.firm, (rm.m + to_months(o.off))::DATE AS M, sum(n) AS f12
FROM rm CROSS JOIN offs o
WHERE o.off <= 11 AND (rm.m + to_months(o.off))::DATE <= (SELECT m FROM data_end)
GROUP BY ALL;

CREATE OR REPLACE TABLE prob_win AS      -- a+c: all reports with the problem (any firm) in the window
SELECT t.product_code, t.problem, (t.m + to_months(o.off))::DATE AS M, sum(t.n) AS p12
FROM (SELECT product_code, problem, m, sum(n) AS n FROM pm GROUP BY ALL) t CROSS JOIN offs o
WHERE o.off <= 11 AND (t.m + to_months(o.off))::DATE <= (SELECT m FROM data_end)
GROUP BY ALL;

CREATE OR REPLACE TABLE tot_win AS       -- N: all reports in the product code in the window
SELECT t.product_code, (t.m + to_months(o.off))::DATE AS M, sum(t.n) AS t12
FROM (SELECT product_code, m, sum(n) AS n FROM rm GROUP BY ALL) t CROSS JOIN offs o
WHERE o.off <= 11 AND (t.m + to_months(o.off))::DATE <= (SELECT m FROM data_end)
GROUP BY ALL;

-- 2x2 tables, PRR / ROR, trend -------------------------------------------------------------
CREATE OR REPLACE TABLE signal_stats AS
WITH j AS (
    SELECT w.product_code, w.firm, w.problem, w.M,
           w.a12::DOUBLE AS a, w.k3, w.base12,
           f.f12::DOUBLE AS ab, pr.p12::DOUBLE AS ac, t.t12::DOUBLE AS n_all
    FROM pm_win w
    JOIN firm_win f  USING (product_code, firm, M)
    JOIN prob_win pr USING (product_code, problem, M)
    JOIN tot_win t   USING (product_code, M)
    WHERE w.a12 >= param('min_reports')::INTEGER
      AND w.M >= param('backtest_start')::DATE
),
c AS (
    SELECT *, ab - a AS b0, ac - a AS c0, n_all - ab - (ac - a) AS d0 FROM j
),
adj AS (   -- Haldane-Anscombe: add 0.5 to every cell when any comparator cell is empty
    SELECT *, (least(b0, c0, d0) <= 0) AS corrected,
           a  + CASE WHEN least(b0, c0, d0) <= 0 THEN 0.5 ELSE 0 END AS a_,
           b0 + CASE WHEN least(b0, c0, d0) <= 0 THEN 0.5 ELSE 0 END AS b_,
           c0 + CASE WHEN least(b0, c0, d0) <= 0 THEN 0.5 ELSE 0 END AS c_,
           d0 + CASE WHEN least(b0, c0, d0) <= 0 THEN 0.5 ELSE 0 END AS d_
    FROM c
),
st AS (
    SELECT *,
        (a_ / (a_ + b_)) / (c_ / (c_ + d_))                                   AS prr,
        sqrt(1/a_ - 1/(a_ + b_) + 1/c_ - 1/(c_ + d_))                          AS se_ln_prr,
        (a_ * d_) / (b_ * c_)                                                  AS ror,
        sqrt(1/a_ + 1/b_ + 1/c_ + 1/d_)                                        AS se_ln_ror,
        (base12 + 0.5) * 3.0 / 12.0                                            AS exp_k3
    FROM adj
)
SELECT product_code, firm, problem, M, a::INTEGER AS a, b0::INTEGER AS b, c0::INTEGER AS c, d0::INTEGER AS d,
       corrected, prr, exp(ln(prr) - 1.96 * se_ln_prr) AS prr_lcl, exp(ln(prr) + 1.96 * se_ln_prr) AS prr_ucl,
       ror, exp(ln(ror) - 1.96 * se_ln_ror) AS ror_lcl, exp(ln(ror) + 1.96 * se_ln_ror) AS ror_ucl,
       k3, base12, exp_k3, poisson_sf(k3::BIGINT, exp_k3) AS trend_p
FROM st;

-- Signals ---------------------------------------------------------------------------------------
-- fire_sensitive / fire_strict (pre-specified): disproportionality (PRR and ROR lower CI above threshold)
--   AND upward trend (Poisson test p below threshold, k3 > expected).
-- fire_fdr (added after the null test showed the pre-specified signals fire in most active firm-months):
--   same disproportionality rule as sensitive, but the trend p-value is Benjamini-Hochberg adjusted across ALL pairs
--   scored in the same month M, and must be below fdr_q.
CREATE OR REPLACE TABLE signal AS
WITH ranked AS (
    SELECT s.*,
           row_number() OVER (PARTITION BY M ORDER BY trend_p, product_code, firm, problem) AS p_rank,
           count(*)     OVER (PARTITION BY M)                                              AS p_n
    FROM signal_stats s
),
bh AS (
    SELECT *,
           least(1.0, min(trend_p * p_n / p_rank) OVER (
               PARTITION BY M ORDER BY p_rank DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS trend_q
    FROM ranked
)
SELECT b.* EXCLUDE (p_rank, p_n), sc.area,
    (prr_lcl > param('sens_prr_lcl')::DOUBLE AND ror_lcl > param('sens_prr_lcl')::DOUBLE
        AND trend_p < param('sens_trend_p')::DOUBLE AND k3 > exp_k3)   AS fire_sensitive,
    (prr_lcl > param('strict_prr_lcl')::DOUBLE AND ror_lcl > param('strict_prr_lcl')::DOUBLE
        AND trend_p < param('strict_trend_p')::DOUBLE AND k3 > exp_k3) AS fire_strict,
    (prr_lcl > param('sens_prr_lcl')::DOUBLE AND ror_lcl > param('sens_prr_lcl')::DOUBLE
        AND trend_q < param('fdr_q')::DOUBLE AND k3 > exp_k3)          AS fire_fdr
FROM bh b
JOIN (SELECT DISTINCT product_code, area FROM scope_code) sc USING (product_code);
