-- FIRMS layer: apply the harmonised manufacturer mapping.
-- Needs table firm_map(firm_norm, firm_std). src/firms.py builds it from clean data and writes the auditable
-- copy to data/clean/firm_map.csv; tests supply their own.

-- Final report table used by the signals. Grain: one row per (report_key, product_code).
CREATE OR REPLACE TABLE event AS
SELECT b.* EXCLUDE (firm_norm),
       coalesce(nullif(m.firm_std, ''), nullif(b.firm_norm, ''), 'UNKNOWN FIRM') AS firm
FROM clean_event_base b
LEFT JOIN firm_map m USING (firm_norm);

-- Final recall table. Grain: one row per recall event x firm x product code.
CREATE OR REPLACE TABLE recall_event AS
SELECT r.res_event_number, r.product_code, s.area,
       coalesce(nullif(m.firm_std, ''), nullif(r.firm_norm, ''), 'UNKNOWN FIRM') AS firm,
       r.recall_date, r.root_cause
FROM clean_recall_base r
JOIN scope_code s USING (product_code)
LEFT JOIN firm_map m USING (firm_norm);
