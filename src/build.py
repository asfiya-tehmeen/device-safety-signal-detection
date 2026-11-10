"""Build the DuckDB pipeline: raw -> clean -> firms -> signals -> baseline -> backtest -> null test.

    python src/build.py                 # full rebuild from data/raw
    python src/build.py --from clean    # rerun from a step (needs earlier tables in the db)

SQL lives in sql/. Python only does what SQL cannot: the Poisson tail function and fuzzy firm matching.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import duckdb
import yaml
from scipy.stats import poisson

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "gold" / "devicewatch.duckdb"

log = logging.getLogger("build")

# (step name, sql file or None for python step)
STEPS = [
    ("macros", "00_macros.sql"),
    ("raw", "01_raw.sql"),
    ("clean", "02_clean.sql"),
    ("firms", "03_firms.sql"),      # python (firms.py) runs inside this step before the SQL
    ("signals", "04_signals.sql"),
    ("baseline", "05_baseline.sql"),
    ("backtest", "06_backtest.sql"),
    ("null", "07_null.sql"),
]


def poisson_sf(k: int | None, mu: float | None) -> float | None:
    """P(X >= k) for X ~ Poisson(mu). Registered as a DuckDB scalar function."""
    if k is None or mu is None:
        return None
    return float(poisson.sf(k - 1, mu))


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "scope.yaml").read_text(encoding="utf-8"))


def setup(con: duckdb.DuckDBPyConnection, cfg: dict) -> None:
    """Register UDFs and create the params and scope_code tables from config."""
    try:
        con.create_function("poisson_sf", poisson_sf, ["BIGINT", "DOUBLE"], "DOUBLE")
    except duckdb.Error:
        pass  # already registered on this connection
    t = cfg["thresholds"]
    rows = {
        "start_date": cfg["date_range"]["start"],
        "backtest_start": cfg["date_range"]["backtest_start"],
        "min_reports": t["min_reports"],
        "lookahead_months": t["recall_lookahead_months"],
        "episode_cooldown_months": t.get("episode_cooldown_months", 6),
        "baseline_sd": t.get("baseline_sd", 2),
        "sens_prr_lcl": t["sensitive"]["prr_lower_ci"], "sens_trend_p": t["sensitive"]["trend_p"],
        "strict_prr_lcl": t["strict"]["prr_lower_ci"], "strict_trend_p": t["strict"]["trend_p"],
        "fdr_q": t.get("fdr_q", 0.05),
    }
    con.execute("CREATE OR REPLACE TABLE params(key VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO params VALUES (?, ?)", [(k, str(v)) for k, v in rows.items()])
    con.execute("CREATE OR REPLACE TABLE scope_code(product_code VARCHAR, area VARCHAR, device_name VARCHAR)")
    con.executemany(
        "INSERT INTO scope_code VALUES (?, ?, ?)",
        [(c, area, name) for area, codes in cfg["areas"].items() for c, name in codes.items()],
    )


def run_sql(con: duckdb.DuckDBPyConnection, filename: str) -> None:
    log.info("running %s", filename)
    con.execute((SQL_DIR / filename).read_text(encoding="utf-8"))


def build(db_path: Path = DB_PATH, start_from: str = "macros") -> duckdb.DuckDBPyConnection:
    os.chdir(ROOT)  # SQL uses project-relative paths
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    # keep memory bounded on a laptop; DuckDB spills to disk beyond this
    con.execute("SET memory_limit = '1500MB'")
    con.execute("SET threads = 2")
    con.execute(f"SET temp_directory = '{(db_path.parent / 'tmp').as_posix()}'")
    setup(con, load_config())
    names = [s[0] for s in STEPS]
    if start_from not in names:
        raise SystemExit(f"unknown step {start_from}; choose from {names}")
    started = False
    for name, sql in STEPS:
        started = started or name == start_from
        # macros are cheap and later steps need them, so they always run
        if name != "macros" and not started:
            continue
        if name == "firms":
            from firms import build_firm_map  # needs the clean tables to exist
            build_firm_map(con)
        run_sql(con, sql)
    return con


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start_from", default="macros", choices=[s[0] for s in STEPS])
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    con = build(Path(args.db), args.start_from)
    print(con.sql("SELECT * FROM dq_summary").df().to_string(index=False))


if __name__ == "__main__":
    main()
