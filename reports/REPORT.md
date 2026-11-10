# DeviceWatch: Would Adverse-Event Signals Have Flagged FDA Recalls Early?

Infusion pumps and ventilators/CPAP, FDA MAUDE reports received 2015-01-01 to 2026-10-30, recalls initiated 2017-01 to 2026-10.
Every number below comes from a file in `reports/` written by `src/report.py` from the DuckDB build.

> **Read this first.** MAUDE is a passive, largely voluntary reporting system whose reports are not verified. FDA states it cannot be used to estimate incidence or establish causation. Reporting rules and reporting behaviour changed over the period, and a single manufacturer accounts for 86.2% of all reports for general infusion pumps (FRN). A flagged firm or device is a question for review, not a finding that it is unsafe. This is a surveillance-style analysis of US public data. It is not FDA's or SFDA's process.

## 1. Findings

**Question.** If a safety team had run disproportionality signals every month, using only the reports FDA had received by that month, how many recalls would it have flagged in advance, how many months early, and with how many false alarms?

**Short answer.** On paper the signals look strong: 78% of recalls were preceded by a signal for the same firm and product code. That number is misleading. The signals fire in 72% of all firm-months in which a firm reports anything, so most recalls of large firms are "flagged" whatever their date. When each recall is moved to 200 random dates, the same rule still "flags" 75%. **As specified, the signals do not beat chance timing, and they do not beat the simple baseline.**

### 1.1 Backtest (279 recall events, 2017-01 to 2026-10, both areas) — `evaluation.csv`

| Method | Recalls flagged in advance | Median lead, months (IQR) | Matured alerts | Precision | False alarms per month |
|---|---|---|---|---|---|
| PRR/ROR + trend, sensitive (pre-specified) | 218 / 279 (78.1%) | 23.1 (16.2 to 23.6) | 188 | 0.261 | 1.48 |
| PRR/ROR + trend, strict (pre-specified) | 202 / 279 (72.4%) | 23.1 (16.6 to 23.5) | 189 | 0.243 | 1.52 |
| PRR/ROR + FDR-adjusted trend (added after the null test) | 217 / 279 (77.8%) | 23.1 (15.9 to 23.5) | 199 | 0.271 | 1.54 |
| **Baseline: month count > 12-month mean + 2 SD** | 203 / 279 (72.8%) | 17.0 (10.4 to 21.4) | 291 | **0.309** | 2.14 |
| Reference: flag every firm-month with ≥ 3 reports | 234 / 279 (83.9%) | 23.3 (19.6 to 23.6) | 202 | 0.198 | 1.72 |

Definitions: an alert is a firm x product code; fires no more than 6 months apart form one alert. A recall is flagged in advance if the method fired for the same firm and product code in the 24 months before the recall date. Precision and false alarms use **matured** alerts only, meaning alerts with a full 24-month follow-up inside the data. There are 94 such months. Lead times are capped at 24 months by that window.

### 1.2 Null test: real recall dates vs random dates — `null_test.csv`, `figures/null_test.png`

The 236 recalls dated 2019-01-01 or later (so that each has a full 24-month look-back) were each given 200 pseudo-random dates in 2019-01 to 2026-10, keeping the same firm and product code.

| Method | Real recall dates | Random dates, mean (95% range) | Lift | p |
|---|---|---|---|---|
| PRR/ROR + trend, sensitive | 0.775 | 0.753 (0.729 to 0.784) | +2.3 pts | 0.080 |
| PRR/ROR + trend, strict | 0.720 | 0.700 (0.674 to 0.729) | +2.0 pts | 0.110 |
| PRR/ROR + FDR trend | 0.775 | 0.750 (0.724 to 0.780) | +2.6 pts | 0.050 |
| Baseline 2 SD | 0.750 | 0.716 (0.674 to 0.763) | +3.4 pts | 0.095 |
| Every active firm-month | 0.831 | 0.823 (0.801 to 0.847) | +0.8 pts | 0.284 |

No method is clearly better than random timing. The FDR variant's p of 0.050 is not evidence: it is one of five methods tested against the same null, and it was added after seeing the first result.

### 1.3 How often each method fires — `alert_load.csv`

| Method | Share of active firm-months flagged |
|---|---|
| PRR/ROR + trend, sensitive | 72.4% |
| PRR/ROR + trend, strict | 60.6% |
| PRR/ROR + FDR trend | 63.4% |
| Baseline 2 SD | 16.6% |

Active firm-month = a firm x product code x month with ≥ 3 reports (4,435 in the backtest period).

### 1.4 What the baseline does better

The 2-SD baseline fires in 16.6% of active firm-months against 72.4% for the sensitive PRR rule. It still flags 72.8% of recalls in advance and has the highest alert precision (0.309, against 0.198 for flagging everything). Its median lead is shorter (17.0 vs 23.1 months), but the PRR rule's 23-month figure mostly reflects being switched on at the start of the window rather than real early warning. Its cost is more separate alerts (291 vs 188) and more false alarms per month (2.14 vs 1.48), because its spikes are short and start new alerts more often. These comparisons are descriptive. They were not tested against each other.

### 1.5 By area — `evaluation.csv`

| Area | Recalls | Sensitive PRR: flagged / precision | Baseline: flagged / precision |
|---|---|---|---|
| Infusion pumps | 158 | 89.2% / 0.225 | 78.5% / 0.329 |
| Ventilators / CPAP | 121 | 63.6% / 0.293 | 65.3% / 0.288 |

### 1.6 Case study: Philips Respironics CPAP/BiPAP (product code BZD), recall initiated 2021-06-14

`case_respironics_bzd_monthly.csv`, `case_respironics_bzd_signals.csv`

- From mid-2019 to April 2021, Respironics filed 1 to 8 BZD reports a month. In May 2021 it filed 87, then 124 in June, 506 in July and 880 in August.
- At the end of May 2021, all three PRR rules fired on the problem term DEGRADED: 87 reports in 12 months, PRR 54.7 (lower 95% CI 7.8), against 0.4 expected in 3 months. That is **0.46 months (about 2 weeks) before the recall**, the lead the strict rule records.
- The sensitive rule is credited with a 13.5-month lead. That comes from a 3-report SMOKING signal in April 2020, which is not plausibly the same issue. The baseline is credited with 9.4 months, from a count jump in August 2020.
- The data cannot say why reports surged in May 2021. It could be the manufacturer's own investigation, or something else. The case shows what the backtest's headline numbers hide: the strongest, most specific signal came only weeks before the recall, and the long "leads" came from weak, unrelated fires.

## 2. Why the signals are almost always on

These are diagnoses from the data, not tested fixes.

1. **Concentration.** CareFusion files 86.2% of all FRN reports (1.37M of 1.59M), and 96.9% of FRN and 95.6% of MEA reports from 2020-11 to 2022-07. For other FRN firms, "all other firms" is mostly one firm's problem mix. For CareFusion, the comparator is a small remainder. A within-product-code comparator breaks down under this concentration.
2. **Manufacturer coding habits.** Each firm uses its own favourite problem terms, so some firm x problem pair always has PRR > 1.
3. **Overdispersion.** A Poisson trend test on large counts calls ordinary month-to-month noise significant. Controlling the false-discovery rate across pairs (the FDR variant) barely changed the firing share (72.4% to 63.4%), so multiplicity is not the main driver.
4. **Coarse alert unit.** Recalls are matched at firm x product code level because recall records do not carry MAUDE problem terms. Large firms have frequent recalls, so any frequent alarm "hits".

## 3. Data — `dq_summary.csv`, `reconciliation.txt`, `headline.json`

| Item | Value |
|---|---|
| Clean reports (one per report x product code) | 2,548,521 (infusion pumps 2,003,774; ventilators/CPAP 544,747) |
| Product codes | FRN 1,590,900; LZG 385,398; MEA 27,476; BZD 304,173; CBK 174,221; MNT 47,462; MNS 11,808; NOU 7,083 |
| Duplicates removed | 1,680 report x device rows |
| Received dates outside range or unparseable | 0 |
| Event dates after receipt or before 1990 (nulled, row kept) | 1,205 |
| Summary reports | 943 |
| Reports with no problem term (labelled explicitly) | 3,118 |
| Recall events in scope (all years) / in the backtest window | 693 / 279 |
| Recalls whose firm appears in MAUDE for that code | 264 of 279 |
| Manufacturers after harmonisation | 382 (139 manual overrides, each with a note in `config/firm_overrides.csv`) |
| Pair-months scored (as-of) | 122,743 |

**Reconciliation with the API.** For every code, clean report counts match the openFDA API total within 0 to 30 reports. The first pull had missed October 2026 for the three infusion codes (5,548 reports), because they were downloaded before FDA had loaded that month. The month-by-month reconciliation found it, and it was re-pulled.

**Reporting artefacts seen.** In BZD, reports rose from a median of about 20 a month to more than 20,000 in June 2022, after the June 2021 Philips recall. That is stimulated reporting after a recall, which is why only alerts *before* a recall date count. FRN and MEA both jumped in late 2020, driven by CareFusion (see section 2).

## 4. Method (short)

- **Pipeline:** DuckDB SQL in `sql/`, running raw → clean → firm harmonisation → signals → baseline → backtest → null test. `python src/build.py` rebuilds everything from `data/raw/` in about 1.5 minutes.
- **Signals:** for each product code x firm x problem term, as of each month M from 2017-01, using reports received in the trailing 12 months (the 12 months ending at M). PRR and ROR come from a 2x2 table against all other firms in the same product code, with 95% CI, a minimum of 3 reports, and a Haldane correction when a cell is empty. The trend test is a Poisson test of the last 3 months against the 12 months before. A signal fires when the lower CI of PRR and ROR exceeds 1 (strict: 2) and the trend p < 0.05 (strict: 0.01). FDR variant: trend p adjusted with Benjamini-Hochberg across all pairs scored in the month, q < 0.05.
- **No future data:** `tests/test_signals.py` recomputes every statistic on data cut off at a month and asserts identical results. A deliberately injected one-month leak makes this test fail.
- **Tests:** 25 tests covering deduplication, date ranges, code vocabularies, firm harmonisation, PRR/ROR against a hand-worked 2x2 table, Benjamini-Hochberg against statsmodels, the no-future-data property, and the backtest and null test on a constructed scenario.

## 5. How this would feed a periodic safety trend report

In a manufacturer's post-market surveillance cycle (for example a periodic trend report or a risk-file review), this pipeline would be the screening layer. It would run monthly and list firm x problem pairs whose reporting rose faster than expected, with the 2x2 counts, PRR/ROR and trend evidence attached. Each would go to a reviewer to decide whether to open an investigation, update the risk file, or close it. The result above says how to use it: as a **triage list ranked by strength of evidence** (like the DEGRADED signal in May 2021), not as an alarm that a firm is heading for a recall. Raw "signal fired" status is too common to act on.

## 6. Limitations

- MAUDE is passive, voluntary for many reporters, and unverified. It gives no incidence rates and no causal evidence.
- There is no denominator (units in use), so large firms report more simply because they sell more.
- Records reflect openFDA's latest version. A problem term or firm name added to a report after it was first received is visible "as of" its original receipt date. The as-of property holds for receipt dates, not for later edits.
- Recalls are an imperfect ground truth. Some problems never lead to a recall, and some recalls are not preceded by reports. Recalls are matched to reports at firm x product code level only.
- Manufacturer harmonisation is at parent level (for example Covidien → Medtronic, Hospira → ICU Medical, Cardinal Health 303 → CareFusion). This keeps recalls and reports joined across ownership changes but merges business units. "ST PAUL" (a city in the manufacturer field) was mapped to Smiths Medical from its brand names (CADD, Medfusion).
- **Known issue, not fixed:** 7,103 reports (0.28%) have no manufacturer name and are grouped as one pseudo-firm, "UNKNOWN FIRM" (mostly MNT, LZG and FRN). It raises alerts that can never match a recall: 7 to 14 per method, for example 10 of the 188 matured alerts for the sensitive rule, all counted as false alarms. Removing it would raise the sensitive rule's precision and lower its false alarms per month a little. It would not change the conclusions. It was left in so that every published number matches the code as run. It appears in the dashboard's firm table.
- US data only. No claim is made about SFDA, EU or any other regulator's process or data.

## 7. Dashboard

A one-page Power BI report (`reports/powerbi/DeviceWatch.pbix`, picture in `reports/powerbi/DeviceWatch_page.png`) shows the same results with a method and area slicer. Its measures are documented, with expected values, in `reports/powerbi/MEASURES.md`.

## 8. What would come next (not done)

- A comparator that survives concentration, for example comparing each firm against its own history rather than against other firms, which is closer to what the baseline does.
- An overdispersion-aware trend test (negative binomial or quasi-Poisson) and a minimum effect size.
- Narrative text to match signals to recall root causes at problem level, not just firm level.
- Pre-registering these changes and testing them on recalls after a fixed cut-off date, so they are not tuned on the same recalls.
