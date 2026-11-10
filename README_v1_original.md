# Project C: Medical Device Safety Signal Detection

**Status:** Not started | **Data:** REAL (openFDA MAUDE and recalls) | **Effort:** about 5 to 6 days
**Target roles:** regulatory affairs (post-market surveillance), medical instrumentation companies, TIC firms

## 1. Business question

Which device types and failure modes show unusually high or rising adverse-event reporting, and do those signals appear before recalls?

## 2. Data

| Source | What | Notes |
|---|---|---|
| openFDA device event API (https://open.fda.gov/apis/device/event) | MAUDE adverse-event reports back to 1992, updated weekly | Check the docs for paging limits. Use bulk MAUDE files if you need more volume (verify on the FDA MAUDE page). |
| openFDA device recall data | Recall records | Ground truth for validating signals. |

Scope to keep it manageable: pick 3 to 5 product areas (for example infusion pumps, insulin pumps, continuous glucose monitors, ventilators).

The FDA states MAUDE data is not validated and cannot support incidence rates or causal claims. Put this in the README and report.

## 3. Setup (PowerShell)

```powershell
cd projects\c-device-safety-signal-detection
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Folder structure

```
data/raw/        API responses or bulk files (never edited)
data/clean/      deduplicated events, labelled narratives
notebooks/       01_ingest, 02_clean, 03_eda, 04_signals, 05_text_model, 06_validate
src/             ingest.py, clean.py, signals.py, text_model.py
tests/           test_clean.py, test_signals.py
reports/         figures and REPORT.md
```

## 5. Tasks

### Phase 1: Ingest (Day 1)
- [ ] Read the openFDA device event and recall docs; note field names and paging limits.
- [ ] Choose product areas and date range; record the choice and reason.
- [ ] Write `src/ingest.py` with retries and caching; download events and recalls.
- [ ] Record counts per product area.

### Phase 2: Clean (Day 2)
- [ ] Deduplicate on report number; handle multiple records per event.
- [ ] Parse dates; resolve date received vs date of event; remove impossible dates.
- [ ] Harmonise manufacturer names (fuzzy matching; manually review the top 50).
- [ ] Standardise product codes and device problem codes; handle missing values explicitly.
- [ ] Note reporting-rule changes over time that may create artificial jumps.
- [ ] Tests: no duplicate report keys; dates in range; code vocabularies valid.

### Phase 3: Explore (Day 2 to 3)
- [ ] Monthly counts per product code.
- [ ] Event-type mix (death, injury, malfunction) and reporter type.
- [ ] Narrative text length and missingness.

### Phase 4: Signal detection (Day 3 to 4)
- [ ] Disproportionality: PRR and ROR with confidence intervals for manufacturer x problem-code pairs; set minimum count thresholds; control for multiple comparisons.
- [ ] Optional: Bayesian shrinkage version.
- [ ] Trend detection: Poisson or negative binomial regression of monthly counts; CUSUM or control charts to flag shifts.

### Phase 5: Text model (Day 4 to 5)
- [ ] Hand-label about 300 narratives into failure modes (define the label set first; write labelling rules).
- [ ] Baseline: keyword rules.
- [ ] Model: TF-IDF + logistic regression; report precision, recall and F1 per class on a held-out set.
- [ ] Optional: topic model (NMF) and compare with your labels.

### Phase 6: Validate (Day 5)
- [ ] For each recall in scope, check whether a signal fired before the recall date and by how many months.
- [ ] Report precision, recall, lead time and false-alarm rate of the signal rules.
- [ ] Try two thresholds and show the trade-off.

### Phase 7: Write up (Day 6)
- [ ] `reports/REPORT.md`: signal list, evaluation table, limitations first.
- [ ] Clean dataset and data dictionary.

## 6. Definition of done

- Pipeline reruns from raw data.
- Signals are evaluated against recalls, with false alarms reported.
- The text classifier beats the keyword baseline or the report says it did not.
- MAUDE's limitations are prominent.

## 7. Limitations

- Voluntary reporting; reporting varies with media attention and rule changes.
- No sales or usage denominator.
- US data; not Saudi or UAE data.

## 8. Do not claim

- That a flagged device is unsafe.
- That this follows SFDA's process. It is a surveillance-style analysis on US public data.

## 9. Resume line template

> Built a device-safety signal pipeline on [N] MAUDE reports; PRR/ROR and CUSUM flagged [N] signals, [N]% preceding FDA recalls by a median of [N] months; narrative classifier reached F1 [x] on a hand-labelled set.
