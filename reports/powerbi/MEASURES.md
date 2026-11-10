# Power BI: tables and DAX measures

Exported by `python src/powerbi.py` from `data/gold/devicewatch.duckdb`. Rebuild the database first (`python src/build.py`).

## Tables to load

| File | Grain | Key columns |
|---|---|---|
| `fact_recall_eval.csv` | method x recall event | `method`, `recall_id`, `area`, `recall_date`, `flagged_in_advance`, `lead_months`, `detectable` |
| `fact_alerts.csv` | method x alert episode | `method`, `area`, `firm`, `alert_month`, `matured`, `followed_by_recall` |
| `fact_signal_fires.csv` | method x pair x month that fired (PRR methods only) | `method`, `area`, `firm`, `problem`, `month`, `prr`, `prr_lcl` |
| `fact_monthly_reports.csv` | month x code x firm | `month`, `area`, `product_code`, `firm`, `reports` |
| `param_eval.csv` | one row | `matured_months` (months in which a matured alert could be raised) |
| `null_test.csv` | method | observed vs random-date flag rate (show as a table; no measures needed) |

Suggested model: a small `dim_method` table (5 rows: `prr_sensitive`, `prr_strict`, `prr_fdr`, `baseline_2sd`, `any_activity`) and a `dim_area` table, each related one-to-many to the three fact tables on `method` / `area`. Set `flagged_in_advance`, `matured`, `followed_by_recall` to True/False type.

## Measures

```DAX
Recalls =
    COUNTROWS ( fact_recall_eval )

Recalls Flagged =
    CALCULATE ( [Recalls], fact_recall_eval[flagged_in_advance] = TRUE () )

Recall Rate =
    DIVIDE ( [Recalls Flagged], [Recalls] )

Median Lead (months) =
    CALCULATE (
        MEDIAN ( fact_recall_eval[lead_months] ),
        fact_recall_eval[flagged_in_advance] = TRUE ()
    )

Alerts (matured) =
    CALCULATE ( COUNTROWS ( fact_alerts ), fact_alerts[matured] = TRUE () )

True Alerts =
    CALCULATE ( [Alerts (matured)], fact_alerts[followed_by_recall] = TRUE () )

False Alarms =
    [Alerts (matured)] - [True Alerts]

Precision =
    DIVIDE ( [True Alerts], [Alerts (matured)] )

False Alarms per Month =
    DIVIDE ( [False Alarms], MAX ( param_eval[matured_months] ) )

Signal Fires =
    COUNTROWS ( fact_signal_fires )
```

Notes:
- `Recalls` counts one row per method per recall, so always slice or filter by method. Without a method filter it multiplies by 5.
- `Signal Fires` only exists for the three PRR methods. The baseline and the "any activity" rule fire at firm level, so their fires are not in this table (their alerts are in `fact_alerts`).
- "Matured" alerts are those with a full 24-month follow-up window inside the data. Precision and false alarms use matured alerts only.
- `False Alarms per Month` uses the whole evaluation period, so it is correct for "all areas". Per area it shows that area's false alarms over the same number of months.

## Expected values (check your page against these)

All areas, all eligible recalls, by method. Computed with pandas from the same tables (`expected_measures.json`), and they match `reports/evaluation.csv` from the SQL pipeline.

| Measure | prr_sensitive | prr_strict | prr_fdr | baseline_2sd | any_activity |
|---|---|---|---|---|---|
| Recalls | 279 | 279 | 279 | 279 | 279 |
| Recalls Flagged | 218 | 202 | 217 | 203 | 234 |
| Recall Rate | 0.781 | 0.724 | 0.778 | 0.728 | 0.839 |
| Median Lead (months) | 23.1 | 23.1 | 23.1 | 17.0 | 23.3 |
| Alerts (matured) | 188 | 189 | 199 | 291 | 202 |
| True Alerts | 49 | 46 | 54 | 90 | 40 |
| False Alarms | 139 | 143 | 145 | 201 | 162 |
| Precision | 0.261 | 0.243 | 0.271 | 0.309 | 0.198 |
| False Alarms per Month | 1.48 | 1.52 | 1.54 | 2.14 | 1.72 |
| Signal Fires | 13,457 | 9,133 | 10,844 | n/a | n/a |

## Suggested page (one page)

1. Card row: Recall Rate, Median Lead, Precision, False Alarms per Month (method slicer, single select).
2. Clustered bar: Recall Rate by method, with the `null_test.csv` random-date rate next to it. This is the key visual: the bars are almost the same height.
3. Line: `fact_monthly_reports` by month and area (log axis), to show the 2021-22 surges.
4. Table: top firms by True Alerts and False Alarms for the selected method.
