-- Shared macros. Run first.

-- Read a parameter from the params table (created by src/build.py from config/scope.yaml).
CREATE OR REPLACE MACRO param(k) AS (SELECT value FROM params WHERE key = k);

-- Manufacturer name normalisation: upper-case, strip punctuation and legal suffixes.
-- Used for both MAUDE manufacturers and recalling firms so the two can be joined.
CREATE OR REPLACE MACRO norm_firm(s) AS
    trim(regexp_replace(
        regexp_replace(
            regexp_replace(upper(coalesce(s, '')), '[^A-Z0-9 ]', ' ', 'g'),
            '\b(INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LLC|LTD|LIMITED|LP|PLC|GMBH|AG|SA|SPA|BV|NV|AB|SRL|PTE|KK|THE)\b',
            ' ', 'g'),
        '\s+', ' ', 'g'));
