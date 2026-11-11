# DeviceWatch: Would Adverse-Event Signals Have Flagged Device Recalls Early?

An as-of backtest of medical device safety signals on 2.55 million FDA MAUDE adverse-event reports, evaluated against 279 FDA recalls, with a DuckDB SQL pipeline, a random-date null test and a Power BI dashboard.

![DeviceWatch Power BI dashboard](reports/powerbi/DeviceWatch_page.png)

## Question

If a post-market surveillance team had run disproportionality signals every month, using only the reports FDA had **received by that month**, how many recalls would it have flagged in advance, how many months early, and how many false alarms would it have raised?

Many MAUDE analyses accidentally use reports that arrived after the event they claim to predict. This project replays the data month by month, and a test proves that no future report is used.

## Results

2,548,521 MAUDE reports (2015-01 to 2026-10), 279 recall events (2017-01 to 2026-10), 2 product areas, 8 product codes.

| Method | Recalls flagged in advance | Median lead (months) | Precision (matured alerts) | False alarms / month | Random-date rate (null) |
|---|---|---|---|---|---|
| PRR/ROR + trend, sensitive | 78.1% | 23.1 | 0.261 | 1.48 | 75.3% (p = 0.080) |
| PRR/ROR + trend, strict | 72.4% | 23.1 | 0.243 | 1.52 | 70.0% (p = 0.110) |
| Baseline: count > 12-month mean + 2 SD | 72.8% | 17.0 | 0.309 | 2.14 | 71.6% (p = 0.095) |
| Reference: every active firm-month | 83.9% | 23.3 | 0.198 | 1.72 | 82.3% |

**The headline numbers look good, and the null test shows why they shouldn't be trusted.** The PRR/ROR signals fire in 72% of active firm-months, so they "flag" random dates almost as often as real recall dates. As specified, they do not beat chance timing or the simple 2-SD baseline. The baseline fires in only 17% of firm-months and has the best precision. In the June 2021 Philips Respironics CPAP recall, the strongest signal (DEGRADED, PRR 54.7) fired about 2 weeks before the recall, not months.

![Real recall dates vs random dates](reports/figures/null_test.png)

*Each box is the share of recalls "flagged in advance" when every recall is moved to 200 random dates (same firm and product code). The red dot is the real recall dates. They sit barely above the boxes, so the signals' timing carries almost no information.*

![Monthly MAUDE reports by product code](reports/figures/monthly_reports.png)

*Reporting surges are visible. CareFusion drives the infusion-pump spike (2021 to 2022), and ventilator/CPAP reports rise sharply after the June 2021 Philips recall (stimulated reporting).*

The full write-up is in [`reports/REPORT.md`](reports/REPORT.md).

## Scope

The two largest product areas on **both** report volume and recall count, from live openFDA counts on 2026-11-09:

| Area | Product codes | MAUDE reports since 2015 | Recalls (all years) |
|---|---|---|---|
| Infusion pumps | FRN (general), LZG (insulin), MEA (PCA) | ~2.0M | 721 + 126 + 46 |
| Ventilators / CPAP | CBK, BZD, MNS, NOU, MNT | ~0.6M | 335 + 83 + 21 + 16 + 64 |

Continuous glucose monitors and automated insulin-delivery pumps were left out: they have millions of reports but too few recalls (10 to 24) to validate against. The codes are fixed in `config/scope.yaml`.

## Method

- **Disproportionality:** PRR and ROR with 95% confidence intervals for manufacturer x problem-code pairs, compared against other manufacturers of the same product code, minimum 3 reports.
- **Trend flag:** Poisson rate test of the last 3 months against the preceding 12. A signal fires when disproportionality **and** the trend flag are both met. A Benjamini-Hochberg FDR variant is reported separately.
- **As-of replay:** for each month from 2017, only reports with `date_received` up to that month are used.
- **Matching to recalls:** recall records are collapsed to recall events (`res_event_number`). A hit is a signal for the same firm and product code before the recall initiation date. A false alarm is a signal with no recall for that firm and product code in the next 24 months. Two thresholds (sensitive, strict) show the trade-off.
- **Baseline:** flag any firm x product-code month with a report count above its 12-month mean + 2 SD.
- **Null test:** each recall date is replaced by 200 random dates (same firm and product code) to separate real timing from firms that are flagged all the time.

## Pipeline (DuckDB SQL: raw → clean → signal)

```
sql/00_macros.sql    norm_firm(), param()
sql/01_raw.sql       load raw openFDA JSON into DuckDB
sql/02_clean.sql     one row per report x in-scope device; dedupe on report number; date checks; recall events
sql/03_firms.sql     harmonised manufacturer names (src/firms.py: rapidfuzz + config/firm_overrides.csv)
sql/04_signals.sql   as-of monthly 2x2 counts, PRR, ROR, 95% CI, minimum count, Poisson trend, BH-FDR variant
sql/05_baseline.sql  2-SD baseline rule and the always-on reference rule
sql/06_backtest.sql  alert episodes, recall hits, lead time, precision, false alarms per month
sql/07_null.sql      random-date null test
src/                 ingest.py (API), build.py (runs the SQL), firms.py, report.py, powerbi.py
tests/               test_clean.py, test_signals.py, test_backtest.py (25 tests)
reports/             REPORT.md, CSV outputs, figures/, powerbi/
```

## Checks

- One command (`python src/build.py`) rebuilds everything from raw data in about 1.5 minutes, and 25 tests pass.
- Counts reconcile to the live openFDA API within 30 reports for every product code (`reports/reconciliation.txt`).
- **No future data:** a test recomputes every statistic on data cut off at a given month and requires identical results. A deliberately injected leak makes it fail.
- Every number in the report and on the dashboard comes from a run.

## Power BI dashboard

[`reports/powerbi/DeviceWatch.pbix`](reports/powerbi/DeviceWatch.pbix) (data embedded) is the page pictured at the top. It has method and area slicers, four KPI cards (recall rate, median lead, precision, false alarms per month), real vs random-date bars, monthly report volume, how often each method fires, and the firms with the most matured alerts.

- DAX measures with the expected value of each: [`reports/powerbi/MEASURES.md`](reports/powerbi/MEASURES.md)
- Build notes: [`reports/powerbi/NOTES.md`](reports/powerbi/NOTES.md)
- The cards use all 279 recalls. The real vs random chart uses the 236 recalls with a full 24-month look-back, which is the fair cohort for that test.
- Rebuild the CSVs with `python src/powerbi.py`. The dashboard was built with AI assistance and verified against the pipeline's results.

## Limitations

- MAUDE is voluntary and unverified. FDA states it cannot be used to estimate incidence rates or show causation.
- There is no sales or usage denominator, so large firms report more simply from market share. Comparing within a product code reduces this but does not remove it. Here one firm, CareFusion, files 86% of general infusion-pump (FRN) reports, including an unexplained surge of about 888k reports in 2022.
- Reports spike after recalls and media coverage, so signals after a recall date do not count as early warning.
- Recalls are an imperfect ground truth: some real problems never lead to a recall. Matching is at firm x product-code level.
- Manufacturer names are harmonised at parent level (for example Covidien into Medtronic).
- 7,103 reports (0.28%) have no manufacturer name and are grouped as "UNKNOWN FIRM". This slightly overstates false alarms but does not change the conclusions.
- US data only. A flagged device or manufacturer is not shown to be unsafe, and this is not FDA's or SFDA's actual signal process.

## Future work

- A comparator that survives market concentration (each firm against its own history), tested on recalls after a fixed cut-off date.
- An overdispersion-aware trend test (negative binomial) and CUSUM; Bayesian shrinkage (EBGM/BCPNN).
- Narrative failure-mode classification, IMDRF code mapping, and periodic safety trend-report formatting.

## Run it

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
$env:OPENFDA_API_KEY = "<your key>"     # free: https://open.fda.gov/apis/authentication/
python src\ingest.py all              # about 1 to 2 hours; resumable
python src\build.py                   # rebuilds data/gold/devicewatch.duckdb (~1.5 min)
python src\report.py                  # reports/*.csv, headline.json, figures
python src\powerbi.py                 # optional: Power BI CSVs
python -m pytest tests -q
```

## Data

| Source | Used for |
|---|---|
| openFDA device event (MAUDE) | Reports: product code, manufacturer, event type, problem codes, `date_received`. Pulled in monthly windows because the API caps paging. |
| openFDA device recall | Ground truth: recalling firm, product code, initiation date, root cause |
| openFDA device classification | Product code to device name and class |

Raw data (455 MB) and the DuckDB database (645 MB) are not in the repository. `python src/ingest.py all` and `python src/build.py` recreate them.

## Tech

Python, DuckDB (SQL), pandas, SciPy, rapidfuzz, matplotlib, pytest, openFDA API, Power BI (DAX).
