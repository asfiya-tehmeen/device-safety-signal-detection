"""Export results from the DuckDB build: tables to reports/*.csv, figures to reports/figures/*.png.

    python src/report.py            # reads data/gold/devicewatch.duckdb
Every number in reports/REPORT.md must come from a file written here.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "gold" / "devicewatch.duckdb"
OUT = ROOT / "reports"
FIG = OUT / "figures"


def export_tables(con: duckdb.DuckDBPyConnection) -> None:
    OUT.mkdir(exist_ok=True)
    q = lambda sql: con.execute(sql).fetchdf()  # noqa: E731

    q("SELECT * FROM dq_summary").to_csv(OUT / "dq_summary.csv", index=False)
    q("SELECT * FROM evaluation ORDER BY population, area, method").to_csv(OUT / "evaluation.csv", index=False)
    q("""SELECT * FROM recall_eval ORDER BY method, recall_date""").to_csv(OUT / "recall_eval.csv", index=False)
    q("SELECT * FROM null_summary ORDER BY method").to_csv(OUT / "null_test.csv", index=False)
    q("""SELECT f.method, count(*) AS firing_firm_months,
                (SELECT count(*) FROM activity_fire) AS active_firm_months,
                round(count(*) * 1.0 / (SELECT count(*) FROM activity_fire), 3) AS share_of_active_firm_months
         FROM fire_month f GROUP BY 1 ORDER BY 1""").to_csv(OUT / "alert_load.csv", index=False)
    # Case study: Philips Respironics CPAP/BiPAP (BZD) before the 2021-06-14 recall
    q("""SELECT date_trunc('month', date_received)::DATE AS month, count(*) AS reports
         FROM event WHERE firm = 'RESPIRONICS' AND product_code = 'BZD'
           AND date_received BETWEEN DATE '2019-06-01' AND DATE '2021-09-30'
         GROUP BY 1 ORDER BY 1""").to_csv(OUT / "case_respironics_bzd_monthly.csv", index=False)
    q("""SELECT M, problem, a AS reports_12m, round(prr, 1) AS prr, round(prr_lcl, 1) AS prr_lcl, k3 AS reports_last_3m,
                round(exp_k3, 1) AS expected_last_3m, fire_sensitive, fire_strict, fire_fdr
         FROM signal WHERE firm = 'RESPIRONICS' AND product_code = 'BZD'
           AND M BETWEEN DATE '2020-01-01' AND DATE '2021-09-01' AND (fire_sensitive OR fire_strict OR fire_fdr)
         ORDER BY M, prr DESC""").to_csv(OUT / "case_respironics_bzd_signals.csv", index=False)
    q("""SELECT a.*, e.followed_by_recall FROM alert a
         LEFT JOIN alert_eval e USING (method, product_code, firm, alert_month, alert_end)
         ORDER BY method, alert_month""").to_csv(OUT / "alerts.csv", index=False)

    # Signal list: first month each (code, firm, problem) fired, with the statistics at that month.
    q("""
        WITH f AS (
            SELECT *, 'prr_sensitive' AS method FROM signal WHERE fire_sensitive
            UNION ALL SELECT *, 'prr_strict' FROM signal WHERE fire_strict
            UNION ALL SELECT *, 'prr_fdr' FROM signal WHERE fire_fdr
        )
        SELECT method, area, product_code, firm, problem, M AS first_fire_month, a AS reports_12m,
               round(prr, 2) AS prr, round(prr_lcl, 2) AS prr_lcl, round(ror, 2) AS ror, round(ror_lcl, 2) AS ror_lcl,
               k3 AS reports_last_3m, round(exp_k3, 2) AS expected_last_3m, trend_p
        FROM f
        QUALIFY row_number() OVER (PARTITION BY method, product_code, firm, problem ORDER BY M) = 1
        ORDER BY method, first_fire_month, firm
    """).to_csv(OUT / "signals.csv", index=False)

    # Headline numbers for the report and resume (one JSON, all from the database).
    s = {}
    s["reports_clean"] = int(q("SELECT count(*) n FROM event").n[0])
    s["reports_by_area"] = {r.area: int(r.n) for r in q("SELECT area, count(*) n FROM event GROUP BY 1").itertuples()}
    s["reports_by_code"] = {r.product_code: int(r.n) for r in q("SELECT product_code, count(*) n FROM event GROUP BY 1").itertuples()}
    s["date_range"] = [str(x) for x in con.execute("SELECT min(date_received), max(date_received) FROM event").fetchone()]
    s["recall_events_total"] = int(q("SELECT count(*) n FROM recall_event").n[0])
    s["recall_events_eligible"] = int(q("SELECT count(DISTINCT res_event_number || product_code || firm) n FROM recall_eval").n[0])
    s["recall_events_firm_in_maude"] = int(q(
        "SELECT count(DISTINCT res_event_number || product_code || firm) n FROM recall_eval WHERE firm_in_maude").n[0])
    s["distinct_firms"] = int(q("SELECT count(DISTINCT firm) n FROM event").n[0])
    s["signal_rows_scored"] = int(q("SELECT count(*) n FROM signal_stats").n[0])
    s["eval_months_matured"] = int(q("SELECT n_months FROM eval_months").n_months[0])
    s["null_population_recalls"] = int(q("SELECT max(n_recalls) n FROM null_summary").n[0])
    s["null_window"] = [str(x) for x in con.execute("SELECT lo, hi FROM null_bounds").fetchone()]
    (OUT / "headline.json").write_text(json.dumps(s, indent=2), encoding="utf-8")


def eda(con: duckdb.DuckDBPyConnection) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    q = lambda sql: con.execute(sql).fetchdf()  # noqa: E731

    monthly = q("""SELECT date_trunc('month', date_received)::DATE AS month, product_code, area, count(*) AS n
                   FROM event GROUP BY ALL ORDER BY 1""")
    monthly.to_csv(OUT / "eda_monthly_counts.csv", index=False)
    q("""SELECT area, product_code, year(date_received) AS yr, event_type, count(*) AS n
         FROM event GROUP BY ALL ORDER BY 1, 2, 3""").to_csv(OUT / "eda_event_type_by_year.csv", index=False)
    q("""SELECT area, coalesce(report_source_code, 'missing') AS reporter, count(*) AS n
         FROM event GROUP BY ALL ORDER BY 1, 3 DESC""").to_csv(OUT / "eda_reporter_mix.csv", index=False)
    q("""SELECT area, is_summary_report, mfr_report_type, count(*) AS n
         FROM event GROUP BY ALL ORDER BY 1, 4 DESC""").to_csv(OUT / "eda_report_type_mix.csv", index=False)
    q("""SELECT * FROM (
             SELECT product_code, firm, count(*) AS n,
                    row_number() OVER (PARTITION BY product_code ORDER BY count(*) DESC) AS rk
             FROM event GROUP BY product_code, firm)
         WHERE rk <= 10 ORDER BY product_code, n DESC""").to_csv(OUT / "eda_top_firms.csv", index=False)
    q("""SELECT product_code, round(median(date_diff('day', date_of_event, date_received)), 0) AS median_lag_days,
                round(quantile_cont(date_diff('day', date_of_event, date_received), 0.9), 0) AS p90_lag_days,
                round(avg((date_of_event IS NULL)::INT), 3) AS share_no_event_date
         FROM event GROUP BY 1 ORDER BY 1""").to_csv(OUT / "eda_event_to_receipt_lag.csv", index=False)

    # Spike investigation: the months where a code's count exceeds 5x its median monthly count.
    q("""WITH m AS (SELECT product_code, date_trunc('month', date_received)::DATE AS month, count(*) AS n FROM event GROUP BY ALL),
              med AS (SELECT product_code, median(n) AS med FROM m GROUP BY 1)
         SELECT m.product_code, m.month, m.n, med.med, round(m.n / med.med, 1) AS x_median
         FROM m JOIN med USING (product_code) WHERE m.n > 5 * med.med ORDER BY m.product_code, m.month""").to_csv(
        OUT / "eda_spike_months.csv", index=False)
    q("""WITH m AS (SELECT product_code, date_trunc('month', date_received)::DATE AS month, count(*) AS n
                    FROM event GROUP BY ALL),
              med AS (SELECT product_code, median(n) AS med FROM m GROUP BY 1),
              spikes AS (SELECT m.product_code, m.month FROM m JOIN med USING (product_code) WHERE m.n > 5 * med.med),
              comp AS (SELECT e.product_code, date_trunc('month', e.date_received)::DATE AS month, e.firm,
                              e.is_summary_report, e.mfr_report_type, count(*) AS n
                       FROM event e JOIN spikes s ON s.product_code = e.product_code
                                                 AND s.month = date_trunc('month', e.date_received)
                       GROUP BY ALL)
         SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY product_code, month ORDER BY n DESC) AS rk FROM comp)
         WHERE rk <= 5 ORDER BY product_code, month, n DESC""").to_csv(OUT / "eda_spike_composition.csv", index=False)

    # Figure 1: monthly reports per code (log scale), one panel per area.
    areas = sorted(monthly.area.unique())
    fig, axes = plt.subplots(len(areas), 1, figsize=(10, 3.6 * len(areas)), sharex=True)
    axes = [axes] if len(areas) == 1 else axes
    for ax, area in zip(axes, areas):
        d = monthly[monthly.area == area]
        for code, g in d.groupby("product_code"):
            ax.plot(g["month"], g["n"], label=code, linewidth=1.3)
        ax.set_yscale("log")
        ax.set_title(f"{area}: MAUDE reports received per month (log scale)")
        ax.set_ylabel("reports")
        ax.legend(ncol=5, fontsize=8, frameon=False)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "monthly_reports.png", dpi=150)
    plt.close(fig)


def eval_figures(con: duckdb.DuckDBPyConnection) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    ev = con.execute("""SELECT * FROM evaluation WHERE area = 'ALL' AND population = 'eligible'""").fetchdf()
    lead = con.execute("SELECT method, lead_months FROM recall_eval WHERE first_fire_month IS NOT NULL").fetchdf()
    colors = {"prr_sensitive": "#1f77b4", "prr_strict": "#d62728", "prr_fdr": "#9467bd",
              "baseline_2sd": "#7f7f7f", "any_activity": "#bcbd22"}

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for m, g in lead.groupby("method"):
        ax[0].hist(g.lead_months, bins=range(0, 26, 2), alpha=0.5, label=m, color=colors.get(m))
    ax[0].set_xlabel("months between first alert and recall")
    ax[0].set_ylabel("recalls flagged in advance")
    ax[0].set_title("Lead time")
    ax[0].legend(frameon=False)
    ax[1].scatter(ev.false_alarms_per_month, ev.recall_rate, s=90, c=[colors.get(m) for m in ev.method])
    for r in ev.itertuples():
        ax[1].annotate(r.method, (r.false_alarms_per_month, r.recall_rate), textcoords="offset points", xytext=(6, 4), fontsize=8)
    ax[1].set_xlabel("false alarms per month (matured alerts)")
    ax[1].set_ylabel("share of recalls flagged in advance")
    ax[1].set_title("Detection vs workload")
    for a in ax:
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "evaluation.png", dpi=150)
    plt.close(fig)


def null_figure(con: duckdb.DuckDBPyConnection) -> None:
    reps = con.execute("SELECT method, rep, avg(hit::INT) AS rate FROM null_recall GROUP BY 1, 2").fetchdf()
    obs = con.execute("SELECT method, observed_rate FROM null_summary").fetchdf()
    order = ["any_activity", "baseline_2sd", "prr_sensitive", "prr_strict", "prr_fdr"]
    fig, ax = plt.subplots(figsize=(9, 4))
    for i, m in enumerate(order):
        r = reps[reps.method == m].rate
        ax.boxplot(r, positions=[i], widths=0.5, showfliers=False)
        ax.scatter([i], obs[obs.method == m].observed_rate, color="#d62728", zorder=3, s=60,
                   label="real recall dates" if i == 0 else None)
    ax.set_xticks(range(len(order)), order)
    ax.set_ylabel("share of recalls flagged in advance")
    ax.set_title("Real recall dates (red) vs 200 random dates for the same firm and product code (box)")
    ax.legend(frameon=False, loc="lower right")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "null_test.png", dpi=150)
    plt.close(fig)


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    export_tables(con)
    eda(con)
    eval_figures(con)
    null_figure(con)
    print((OUT / "headline.json").read_text(encoding="utf-8"))
    print(con.execute("SELECT * FROM evaluation ORDER BY population, area, method").fetchdf().to_string(index=False))


if __name__ == "__main__":
    main()
