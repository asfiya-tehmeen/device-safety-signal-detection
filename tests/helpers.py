"""Test helpers: write synthetic raw openFDA files and run the real SQL pipeline on them."""
from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build  # noqa: E402

CFG = {
    "date_range": {"start": "2015-01-01", "end": None, "backtest_start": "2017-01-01"},
    "areas": {"test_area": {"AAA": "Test device A", "BBB": "Test device B"}},
    "thresholds": {
        "min_reports": 3, "recall_lookahead_months": 24, "episode_cooldown_months": 6, "baseline_sd": 2,
        "sensitive": {"prr_lower_ci": 1.0, "trend_p": 0.05},
        "strict": {"prr_lower_ci": 2.0, "trend_p": 0.01},
    },
}


def event(report_number, received, firm, code="AAA", problems=("X",), event_type="Malfunction",
          date_of_event=None, extra_devices=(), summary="N"):
    """One raw MAUDE report in openFDA JSON shape (only the fields the pipeline reads)."""
    devices = [{"brand_name": "b", "generic_name": "g", "manufacturer_d_name": firm, "model_number": "m",
                "device_report_product_code": code}]
    for c in extra_devices:
        devices.append({"brand_name": "b", "generic_name": "g", "manufacturer_d_name": firm,
                        "model_number": "m", "device_report_product_code": c})
    return {
        "report_number": report_number, "mdr_report_key": report_number, "event_key": "",
        "date_received": received, "date_of_event": date_of_event if date_of_event is not None else received,
        "event_type": event_type, "type_of_report": ["Initial submission"], "mfr_report_type": "Initial",
        "summary_report_flag": summary, "report_source_code": "Manufacturer report",
        "manufacturer_name": firm, "product_problems": list(problems), "device": devices,
    }


def recall(res_event, code, firm, initiated, product_res="Z-0001-2018"):
    return {
        "product_res_number": product_res, "res_event_number": res_event, "product_code": code,
        "recalling_firm": firm, "event_date_initiated": initiated, "event_date_posted": initiated,
        "recall_status": "Terminated", "root_cause_description": "Device Design",
        "reason_for_recall": "r", "product_description": "d",
    }


def _write_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def write_raw(root: Path, event_files: dict[str, list[dict]], recalls: list[dict]) -> None:
    """event_files: {'AAA/part1': [events...]} -> data/raw/event/AAA/part1.jsonl.gz"""
    for name, rows in event_files.items():
        _write_gz(root / "data" / "raw" / "event" / f"{name}.jsonl.gz", rows)
    _write_gz(root / "data" / "raw" / "recall" / "ALL.jsonl.gz", recalls or [recall("0", "AAA", "NOBODY", "2000-01-01")])
    _write_gz(root / "data" / "raw" / "classification.jsonl.gz",
              [{"product_code": "AAA", "device_name": "Test device A", "device_class": "2",
                "medical_specialty_description": "General"}])


def run_pipeline(root: Path, event_files: dict[str, list[dict]], recalls: list[dict] | None = None,
                 cfg: dict = CFG, until: str = "null") -> duckdb.DuckDBPyConnection:
    """Run the real SQL (macros -> raw -> clean -> firms -> signals -> baseline -> backtest) on synthetic raw files.

    Firm mapping is the identity (firm_norm -> firm_norm); fuzzy matching has its own unit test.
    """
    write_raw(root, event_files, recalls or [])
    old = os.getcwd()
    os.chdir(root)
    try:
        con = duckdb.connect()
        build.setup(con, cfg)
        order = ["00_macros.sql", "01_raw.sql", "02_clean.sql"]
        for f in order:
            build.run_sql(con, f)
        con.execute("""CREATE OR REPLACE TABLE firm_map AS
                       SELECT firm_norm, firm_norm AS firm_std FROM
                       (SELECT firm_norm FROM clean_event_base UNION SELECT firm_norm FROM clean_recall_base)""")
        for f in ["03_firms.sql", "04_signals.sql", "05_baseline.sql", "06_backtest.sql", "07_null.sql"]:
            build.run_sql(con, f)
            if f.startswith({"firms": "03", "signals": "04", "baseline": "05", "backtest": "06", "null": "07"}[until]):
                break
        return con
    finally:
        os.chdir(old)
