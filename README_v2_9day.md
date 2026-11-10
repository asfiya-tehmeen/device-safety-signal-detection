# Project C: DeviceWatch — Can Adverse-Event Data Warn You Before a Recall?

**Status:** Not started | **Data:** REAL (openFDA MAUDE, recalls, enforcement, classification) | **Effort:** about 8 to 9 days (core 6, stretch 2 to 3)
**Target roles:** post-market surveillance (PMS) / vigilance analyst, regulatory affairs, quality and risk management at medtech companies, TIC and notified bodies, healthcare data analyst
**Original plan:** kept in [`README_v1_original.md`](README_v1_original.md)

## 1. Why this version is different

Most portfolio projects on MAUDE stop at "I calculated PRR". A PMS team does not hire for a formula. It hires for someone who can run the **monthly signal review**: find what changed, decide what is worth a look, and write it up so a quality board can act. This project is built around that job.

Four things set it apart:

1. **An honest backtest, not hindsight.** Signals are computed month by month using only reports the FDA had *received by that month* (an "as-of" replay). Most MAUDE projects accidentally use future data. This one measures real lead time before recalls, and the false-alarm cost of getting it.
2. **Regulatory language, not just statistics.** Failure modes are mapped to IMDRF adverse-event codes (the terminology FDA, EU and other regulators use), output is written as a trend-report section in the style EU MDR Article 88 and ISO 14971 risk-file updates expect.
3. **Three generations of text classification on the same labels:** keyword rules → TF-IDF + logistic regression → an LLM classifier, with F1, cost per 1,000 reports and error analysis for each. Shows judgement about when an LLM is worth it.
4. **A reviewer-facing product:** a Streamlit signal-review app with a triage queue and a one-click monthly signal brief, on top of a tested DuckDB pipeline (bronze → silver → gold).

## 2. Business questions

| # | Question | Who asks it |
|---|---|---|
| Q1 | Which device problems for which manufacturers are reported disproportionately often compared with competitors making the same device type? | PMS analyst, quality |
| Q2 | Which of those problems are *rising*, and when did the shift start? | PMS analyst, risk management |
| Q3 | If a PMS team had run these rules every month, how many recalls would they have seen coming, how many months early, and how many false alarms would they have chased? | Head of quality, regulatory affairs |
| Q4 | What failure modes do the narratives describe, and do they match the root cause the manufacturer gave in the recall? | Quality engineering, CAPA owners |
| Q5 (stretch) | How long after an FDA recall does the same issue appear in GCC regulator safety notices? | GCC regulatory affairs, distributors, TIC |

Q3 is the headline. Everything else feeds it.

## 3. Scope

Pick 4 product areas with enough reports **and** enough recalls to validate against. Proposed (confirm counts in Phase 1 before committing):

| Product area | Why it is a good test | Candidate case study (verify dates in recall data) |
|---|---|---|
| Infusion pumps | High volume, many recalls, software and hardware failures | Several large-volume pump recalls |
| Insulin pumps | Patient-operated, mix of mechanical and software failures | Medtronic MiniMed 600-series retainer ring (2019 to 2020) |
| Continuous glucose monitors | Fast-growing, high report volume, sensor and app failures | Pick from recall list in Phase 1 |
| CPAP / BiPAP / ventilators | Includes a known massive signal, a stress test for reporting artefacts | Philips foam recall (June 2021) |

Date range: 2015 to latest available. Each product area is defined by a fixed list of FDA product codes (looked up in the device classification endpoint), recorded in `config/scope.yaml`.

## 4. Data

| Source | What | Used for |
|---|---|---|
| openFDA device event (https://open.fda.gov/apis/device/event) | MAUDE reports: product code, manufacturer, event type, device problems, date received, narratives | Signals and text model |
| openFDA bulk downloads (https://open.fda.gov/data/downloads) | Quarterly zipped JSON of the same data | Volume beyond API paging limits (API returns max 1,000 per call and limits `skip`) |
| openFDA device recall + enforcement | Recall date, firm, product code, root cause, recall class (I, II, III) | Ground truth for Q3 and Q4 |
| openFDA device classification | Product code → device name, device class, panel | Scope definition, joins |
| IMDRF AE terminology (Annex A device problem codes) | Standard failure-mode hierarchy | Label set for the text model |
| Stretch: SFDA and UAE regulator safety notices / recalls (verify what is public and scrapeable first) | GCC field safety notices | Q5 |

### Known reporting artefacts (must be handled, not ignored)
- **Summary reporting:** Alternative Summary Reporting (ASR) data released in 2019 and Voluntary Malfunction Summary Reporting (VMSR, from 2019) create batch and quarterly spikes that are not real changes in device performance.
- **Stimulated reporting:** after a recall or news coverage, reports jump. Signals *after* a recall date do not count as early warning.
- **Litigation-driven reports** (often filed years after the event): use `date_received` for signal timing, report the event-to-receipt lag distribution.
- **Multiple devices / patients per report and supplemental reports:** deduplicate on report key, keep the latest version.

## 5. Method

### 5.1 Pipeline (data engineering)
```
bronze  raw API pages and bulk files, never edited (data/raw)
silver  one row per report, one row per report x device problem, harmonised firm names (data/clean)
gold    monthly counts per product code x firm x problem; signal table; recall table (DuckDB)
```
- Retries, caching and incremental pulls (re-running only fetches new quarters).
- Data-quality tests in `pytest`: unique report keys, dates in range, product codes in classification table, problem codes in vocabulary, row counts reconcile bronze → silver.
- Firm harmonisation: `rapidfuzz` + manual review of top 50, saved as a mapping file so it is auditable.

### 5.2 Signal detection
Comparator: other manufacturers **of the same product code** (like-for-like competitor background, which is what a manufacturer's PMS team would use).

| Method | What it adds |
|---|---|
| PRR and ROR with 95% CI, minimum 3 reports | The standard pharmacovigilance screen; easy to explain |
| Bayesian shrinkage (BCPNN information component, or MGPS/EBGM, the empirical Bayes approach FDA uses on FAERS) | Stops small counts from producing huge, noisy ratios |
| Benjamini-Hochberg FDR control | Thousands of firm x problem pairs are tested |
| Negative binomial regression of monthly counts with an artefact indicator for VMSR quarters | Trend with overdispersion handled |
| CUSUM on monthly counts per pair | Detects *when* a shift started |

A **signal** fires when a pair crosses the disproportionality threshold **and** CUSUM detects an upward shift. Two threshold settings (sensitive vs strict) are compared.

### 5.3 As-of backtest (the core of Q3)
For every month M from 2017 onward: keep only reports with `date_received` ≤ M, recompute signals, record which pairs fire. Then for each in-scope recall:
- **Hit:** a signal for the same firm and product code (and, where mappable, a related problem) fired before the recall initiation date.
- **Lead time:** months between first signal and recall.
- **False alarm:** a signal with no recall for that firm and product code within 24 months.

Reported: recall-level recall (sensitivity), signal-level precision, median lead time with IQR, false alarms per month a reviewer would have had to triage, broken down by recall class (Class I matters most). A naive baseline ("flag any pair whose count doubled versus last year") is included so the method has something to beat.

### 5.4 Narrative failure-mode classifier (Q4)
- Label set: 8 to 12 failure modes mapped to IMDRF Annex A level-1/level-2 terms (e.g. *software*, *power/battery*, *occlusion/flow*, *alarm*, *sensor accuracy*, *mechanical/material*, *use error*, *connectivity*, *other/insufficient info*). Labelling rules written **before** labelling.
- Hand-label 400 narratives (stratified by product area); 80 double-labelled on a second pass a week later to report self-agreement (Cohen's kappa).
- Models compared on the same held-out set:

| Model | Report |
|---|---|
| Keyword rules | Macro F1, per-class P/R |
| TF-IDF + logistic regression | Macro F1, per-class P/R, top features per class |
| LLM (zero-shot, then few-shot with labelling rules in the prompt) | Macro F1, per-class P/R, cost and time per 1,000 reports, disagreement examples |

- Then apply the best model to all in-scope narratives and compare the dominant failure mode in the months before each recall with the recall's `root_cause_description`.

### 5.5 Stretch: GCC lag analysis (Q5)
Collect SFDA (and if available UAE) medical device safety notices for the same firms and product areas, match to FDA recalls, and report the share that appear in the GCC and the median lag. First step is checking what is actually published; drop this if the data is not there, and say so.

## 6. Deliverables

| Deliverable | Audience |
|---|---|
| `reports/REPORT.md`: limitations first, then backtest results, signal list, case studies | Hiring manager, technical reviewer |
| `reports/signal_brief_YYYY-MM.md`: auto-generated monthly brief written as a PMS trend-report section (signal, evidence, IMDRF code, suggested action: monitor / investigate / risk-file review) | Shows you know the workflow |
| Streamlit app: product area and firm filters, signal table with triage status, trend + CUSUM chart per signal, narrative examples, recall overlay | Demo in interviews (2-minute screen share) |
| Clean dataset + data dictionary + firm mapping file | Reproducibility |
| 1-page case study on the CPAP foam signal: when would this pipeline have flagged it? | LinkedIn post and interview story |

## 7. Folder structure

```
config/          scope.yaml (product codes, date range, thresholds)
data/raw/        bronze: API responses and bulk files (never edited)
data/clean/      silver: deduplicated reports, labels, firm mapping
data/gold/       devicewatch.duckdb
notebooks/       01_ingest, 02_clean, 03_eda, 04_signals, 05_backtest, 06_text_model, 07_case_study
src/             ingest.py, clean.py, signals.py, backtest.py, text_model.py, brief.py
app/             streamlit_app.py
tests/           test_clean.py, test_signals.py, test_backtest.py
reports/         figures, REPORT.md, signal briefs
```

## 8. Plan

| Phase | Days | Output | Done when |
|---|---|---|---|
| 1. Scope and ingest | 1 | `scope.yaml`, bronze data, counts per product area, recall counts per area | Each area has enough reports and at least 5 recalls, or is swapped |
| 2. Clean (silver) | 1 | Deduplicated tables, firm mapping, artefact flags, tests passing | Tests green; bronze → silver row counts reconcile |
| 3. EDA | 0.5 | Monthly volumes, event-type mix, reporter mix, event-to-receipt lag, artefact spikes annotated | Every spike on the charts is explained or marked unexplained |
| 4. Signals | 1.5 | PRR/ROR, shrinkage, FDR, NB regression, CUSUM; signal table | Unit tests on PRR/ROR against hand-worked 2x2 tables |
| 5. Backtest | 1 | As-of replay, hit/lead/false-alarm table, threshold trade-off, naive baseline | Results hold with no future data (test checks it) |
| 6. Text model | 1.5 | 400 labels, 3 models compared, root-cause comparison | Best model chosen on held-out F1, cost reported |
| 7. Product + write-up | 1 | Streamlit app, monthly brief generator, REPORT.md, case study | Pipeline reruns from raw with one command |
| 8. Stretch | 1 to 2 | GCC lag analysis, GitHub Actions running tests | |

## 9. Definition of done

- One command rebuilds everything from raw data.
- Backtest uses only data available at each month, and a test proves it.
- Signals are evaluated against recalls with lead time **and** false-alarm rate, against a naive baseline.
- Text models are compared honestly; if the LLM does not beat TF-IDF enough to justify cost, the report says so.
- MAUDE limitations are the first section of the report.

## 10. Limitations (say these first)

- MAUDE is passive, voluntary for many reporters, and not validated. The FDA states it cannot be used to estimate incidence or establish causation.
- No denominator (units sold or in use), so a big manufacturer gets more reports simply from market share. Within-product-code comparison reduces but does not remove this.
- Reporting changes with recalls, media and rule changes (summary reporting).
- Recalls are an imperfect ground truth: some real problems never lead to a recall, and some recalls are not preceded by reports.
- US data only. GCC regulators run their own vigilance systems.

## 11. Do not claim

- That a flagged device or manufacturer is unsafe.
- That this replicates FDA, EU or SFDA internal signal processes. It is a surveillance-style analysis on US public data, using methods from the published pharmacovigilance and device-surveillance literature.

## 12. Resume line templates

> Built a post-market surveillance pipeline on [N] FDA MAUDE reports across [4] device areas; in an as-of monthly backtest, disproportionality + CUSUM signals preceded [N]% of [N] recalls (Class I: [N]%) by a median of [N] months, at [N] false alarms per month.

> Classified [N] device narratives into IMDRF-aligned failure modes; TF-IDF model reached macro F1 [x] vs [y] for keyword rules and [z] for an LLM at $[c] per 1,000 reports, on [400] hand-labelled reports.

> Shipped a Streamlit signal-review tool and auto-generated monthly signal briefs on a tested DuckDB pipeline (bronze/silver/gold).

## 13. Interview story (why you built it this way)

At TUV Rheinland I worked on GCC certification and ISO 17025 / ISO 9001 quality systems, where the question is always "what evidence would convince an auditor?". This project applies the same lens to post-market surveillance: not "can I compute a signal", but "would this signal have helped someone act before the recall, and what would it have cost them in false alarms?"
