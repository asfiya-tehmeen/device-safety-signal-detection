# DeviceWatch report notes

- Power BI Desktop reserves the table name `Measures`. The dedicated table is named `_Measures`. The ten DAX expressions in `MEASURES.md` are unchanged.
- The Method slicer defaults to `prr_sensitive`. The four cards and the firm table use the selected method and area. The MAUDE trend responds to Area. Both cross-method charts always show both areas because their input files contain method-level results only.
- The real-versus-random comparison uses the observed rate and mean random-date rate from the full-look-back cohort in `null_test.csv`. The Recall Rate card uses the broader backtest cohort in `fact_recall_eval.csv`.
- The firing-frequency chart uses `../alert_load.csv` as an additional Power Query source. It measures the share of active firm-months with a fire. The cards and firm table count matured episodes, which can span multiple fires. The baseline fires in fewer firm-months and yields more separate matured episodes than `prr_sensitive`.
- The firm table ranks by matured episodes (True Alerts plus False Alarms). The monthly denominator for False Alarms per Month stays fixed when selecting an area, as specified in `MEASURES.md`.
- If the project is moved, update its Power Query `DataFolder` parameter to point to the six report input CSVs. The firing-frequency CSV is expected one folder above them.
- Verification used the four rendered cards with each method selected in Desktop, plus a DAX query against the saved PBIX model for all ten specified measures. `Signal Fires` returns DAX BLANK for the two non-PRR methods because their rows are absent from the signal-fires table.
- The PNG was rendered from Power BI Desktop’s PDF page export with the print margin removed. The static image shows the visible rows of the scrollable firm table.
