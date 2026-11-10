"""Export flat tables for a Power BI page to reports/powerbi/, and compute the expected value of every DAX measure
in MEASURES.md with pandas (same definitions), so the Power BI page can be checked against the pipeline.

    python src/powerbi.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "gold" / "devicewatch.duckdb"
OUT = ROOT / "reports" / "powerbi"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    q = lambda sql: con.execute(sql).fetchdf()  # noqa: E731

    alerts = q("""
        SELECT a.method, s.area, a.product_code, a.firm, a.alert_month, a.alert_end,
               (e.alert_month IS NOT NULL) AS matured,
               coalesce(e.followed_by_recall, FALSE) AS followed_by_recall
        FROM alert a
        JOIN (SELECT DISTINCT product_code, area FROM scope_code) s USING (product_code)
        LEFT JOIN alert_eval e USING (method, product_code, firm, alert_month, alert_end)
        ORDER BY method, alert_month""")
    recalls = q("""
        SELECT method, res_event_number || '|' || product_code || '|' || firm AS recall_id,
               res_event_number, area, product_code, firm, recall_date, detectable, firm_in_maude,
               first_fire_month, round(lead_months, 2) AS lead_months,
               (first_fire_month IS NOT NULL) AS flagged_in_advance
        FROM recall_eval ORDER BY method, recall_date""")
    fires = q("""
        SELECT 'prr_sensitive' AS method, area, product_code, firm, problem, M AS month, a, prr, prr_lcl, ror, ror_lcl,
               k3, exp_k3, trend_p FROM signal WHERE fire_sensitive
        UNION ALL SELECT 'prr_strict', area, product_code, firm, problem, M, a, prr, prr_lcl, ror, ror_lcl, k3, exp_k3, trend_p
        FROM signal WHERE fire_strict
        UNION ALL SELECT 'prr_fdr', area, product_code, firm, problem, M, a, prr, prr_lcl, ror, ror_lcl, k3, exp_k3, trend_p
        FROM signal WHERE fire_fdr""")
    monthly = q("""SELECT date_trunc('month', date_received)::DATE AS month, area, product_code, firm, count(*) AS reports
                   FROM event GROUP BY ALL ORDER BY 1""")
    params = q("SELECT n_months AS matured_months FROM eval_months")

    alerts.to_csv(OUT / "fact_alerts.csv", index=False)
    recalls.to_csv(OUT / "fact_recall_eval.csv", index=False)
    fires.to_csv(OUT / "fact_signal_fires.csv", index=False)
    monthly.to_csv(OUT / "fact_monthly_reports.csv", index=False)
    params.to_csv(OUT / "param_eval.csv", index=False)
    q("SELECT * FROM null_summary").to_csv(OUT / "null_test.csv", index=False)

    # Expected measure values (all areas, all populations = 'eligible'), per method.
    months = int(params.matured_months[0])
    expected = {}
    for m in sorted(recalls.method.unique()):
        r = recalls[recalls.method == m]
        a = alerts[(alerts.method == m) & alerts.matured]
        flagged = r[r.flagged_in_advance]
        true_alerts = int(a.followed_by_recall.sum())
        expected[m] = {
            "Signal Fires": int((fires.method == m).sum()),
            "Recalls": int(len(r)),
            "Recalls Flagged": int(len(flagged)),
            "Recall Rate": round(len(flagged) / len(r), 3),
            "Median Lead (months)": round(float(flagged.lead_months.median()), 1),
            "Alerts (matured)": int(len(a)),
            "True Alerts": true_alerts,
            "False Alarms": int(len(a) - true_alerts),
            "Precision": round(true_alerts / len(a), 3) if len(a) else None,
            "False Alarms per Month": round((len(a) - true_alerts) / months, 2),
        }
    (OUT / "expected_measures.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    print(json.dumps(expected, indent=2))


if __name__ == "__main__":
    main()
