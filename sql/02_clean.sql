-- CLEAN layer. Needs: raw_event, raw_recall, scope_code(product_code, area), params(key, value).
-- Grain of clean_event_base: one row per (report_key, product_code).

-- 1) One row per report x in-scope device (a report can list several devices).
CREATE OR REPLACE TABLE stg_event AS
SELECT
    nullif(trim(coalesce(nullif(trim(t.report_number), ''), t.mdr_report_key)), '') AS report_key,
    t.date_received, t.date_of_event, t.event_type, t.type_of_report,
    t.mfr_report_type, t.summary_report_flag, t.report_source_code,
    coalesce(nullif(trim(t.manufacturer_name), ''), nullif(trim(t.d['manufacturer_d_name']), '')) AS firm_raw,
    t.product_problems, t.filename,
    t.d['device_report_product_code']                                         AS product_code
FROM (SELECT *, unnest(device) AS d FROM raw_event) t
JOIN scope_code s ON s.product_code = t.d['device_report_product_code'];

-- 2) Deduplicate on report key + product code (the same report can be fetched from two code folders,
--    and the same report can list two devices with the same code). Keep the latest received version.
CREATE OR REPLACE TABLE stg_event_dedup AS
SELECT * FROM stg_event
WHERE report_key IS NOT NULL
QUALIFY row_number() OVER (
    PARTITION BY report_key, product_code
    ORDER BY date_received DESC, filename DESC
) = 1;

-- 3) Date checks.
--    received date must parse and fall in [start_date, today]; event date is nulled (not dropped) if impossible.
CREATE OR REPLACE TABLE clean_event_base AS
SELECT
    report_key, product_code,
    s.area,
    try_strptime(date_received, '%Y%m%d')::DATE                                          AS date_received,
    CASE WHEN try_strptime(date_of_event, '%Y%m%d')::DATE
              BETWEEN DATE '1990-01-01' AND try_strptime(date_received, '%Y%m%d')::DATE
         THEN try_strptime(date_of_event, '%Y%m%d')::DATE END                            AS date_of_event,
    (try_strptime(date_of_event, '%Y%m%d') IS NOT NULL AND
     NOT (try_strptime(date_of_event, '%Y%m%d')::DATE
          BETWEEN DATE '1990-01-01' AND try_strptime(date_received, '%Y%m%d')::DATE))    AS event_date_invalid,
    coalesce(nullif(trim(event_type), ''), 'Unknown')                                    AS event_type,
    (upper(coalesce(summary_report_flag, '')) = 'Y')                                     AS is_summary_report,
    mfr_report_type, report_source_code,
    firm_raw, norm_firm(firm_raw)                                                         AS firm_norm,
    product_problems
FROM stg_event_dedup e
JOIN scope_code s USING (product_code)
WHERE try_strptime(date_received, '%Y%m%d')::DATE
      BETWEEN (SELECT value::DATE FROM params WHERE key = 'start_date') AND current_date;

-- 4) One row per report x product code x problem term. Reports with no problem term get an explicit label
--    (missing values are handled explicitly, not dropped).
CREATE OR REPLACE TABLE event_problem AS
SELECT DISTINCT report_key, product_code, upper(trim(p)) AS problem
FROM (SELECT report_key, product_code, unnest(product_problems) AS p FROM clean_event_base)
WHERE p IS NOT NULL AND trim(p) <> ''
UNION
SELECT report_key, product_code, 'NO PROBLEM REPORTED'
FROM clean_event_base
WHERE product_problems IS NULL OR len(product_problems) = 0;

-- Uninformative terms: kept in the data, excluded from signal screening.
CREATE OR REPLACE TABLE problem_generic AS
SELECT * FROM (VALUES
    ('NO PROBLEM REPORTED'),
    ('ADVERSE EVENT WITHOUT IDENTIFIED DEVICE OR USE PROBLEM'),
    ('INSUFFICIENT INFORMATION'),
    ('INSUFFICIENT DEVICE PROBLEM INFORMATION'),
    ('NO KNOWN DEVICE PROBLEM'),
    ('APPROPRIATE TERM/CODE NOT AVAILABLE'),
    ('NO APPARENT ADVERSE EVENT'),
    ('NO CLINICAL SIGNS, SYMPTOMS OR CONDITIONS')
) AS t(problem);

-- 5) Recall events: FDA recall rows are per product; collapse to one row per recall event x firm x product code.
CREATE OR REPLACE TABLE clean_recall_base AS
SELECT
    res_event_number, product_code,
    any_value(recalling_firm)                                           AS firm_raw,
    norm_firm(any_value(recalling_firm))                                AS firm_norm,
    min(try_strptime(event_date_initiated, '%Y-%m-%d')::DATE)           AS recall_date,
    any_value(root_cause_description)                                   AS root_cause,
    count(*)                                                            AS n_product_rows
FROM raw_recall
WHERE res_event_number IS NOT NULL
  AND product_code IN (SELECT product_code FROM scope_code)
GROUP BY res_event_number, product_code, norm_firm(recalling_firm)
HAVING min(try_strptime(event_date_initiated, '%Y-%m-%d')::DATE) IS NOT NULL;

-- 6) Data-quality summary (used by tests and the report).
CREATE OR REPLACE TABLE dq_summary AS
SELECT 'raw_event_rows' AS metric, (SELECT count(*) FROM raw_event)::BIGINT AS value
UNION ALL SELECT 'in_scope_report_device_rows', (SELECT count(*) FROM stg_event)
UNION ALL SELECT 'duplicates_removed', (SELECT count(*) FROM stg_event) - (SELECT count(*) FROM stg_event_dedup)
UNION ALL SELECT 'dropped_bad_received_date', (SELECT count(*) FROM stg_event_dedup) - (SELECT count(*) FROM clean_event_base)
UNION ALL SELECT 'clean_event_rows', (SELECT count(*) FROM clean_event_base)
UNION ALL SELECT 'event_date_invalid_nulled', (SELECT count(*) FROM clean_event_base WHERE event_date_invalid)
UNION ALL SELECT 'summary_reports', (SELECT count(*) FROM clean_event_base WHERE is_summary_report)
UNION ALL SELECT 'reports_without_problem_term', (SELECT count(*) FROM event_problem WHERE problem = 'NO PROBLEM REPORTED')
UNION ALL SELECT 'recall_events', (SELECT count(*) FROM clean_recall_base);
