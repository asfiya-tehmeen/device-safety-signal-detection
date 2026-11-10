"""Cleaning tests: duplicates, date ranges, vocabularies, scope, firm harmonisation, recall collapse."""
from datetime import date

from helpers import event, recall, run_pipeline
import firms


def _clean_con(tmp_path):
    rows = [
        event("R1", "20200105", "Acme Corp.", problems=("Failure to Fire", "Leak")),
        event("R1", "20200105", "Acme Corp.", problems=("Failure to Fire", "Leak")),   # exact duplicate in same file
        event("R2", "20200110", "Acme Corp.", code="AAA", extra_devices=("BBB",)),      # two in-scope devices
        event("R3", "20200115", "Beta Inc", problems=()),                               # no problem term
        event("R4", "20200120", "Beta Inc", code="ZZZ"),                                # out of scope
        event("R5", "20991231", "Beta Inc"),                                            # received in the future
        event("R6", "not-a-date", "Beta Inc"),                                          # unparseable
        event("R7", "20140101", "Beta Inc"),                                            # before start_date
        event("R8", "20200201", "Beta Inc", date_of_event="20210101"),                  # event after receipt
        event("R9", "20200202", "Beta Inc", date_of_event="19500101"),                  # event implausibly old
        event("R10", "20200203", "Beta Inc", problems=("  leak ",)),                    # case/space variants
        event("", "20200204", "Beta Inc"),                                              # no report number and no key -> dropped
    ]
    # R1 also arrives from a second code folder (a report listing two devices is fetched under both codes)
    other_folder = [event("R1", "20200105", "Acme Corp.", problems=("Failure to Fire", "Leak"))]
    return run_pipeline(tmp_path, {"AAA/a": rows, "BBB/a": other_folder}, until="firms")


def test_no_duplicate_report_keys(tmp_path):
    con = _clean_con(tmp_path)
    dup = con.execute("""SELECT report_key, product_code, count(*) FROM clean_event_base
                     GROUP BY 1, 2 HAVING count(*) > 1""").fetchall()
    assert dup == []
    assert con.execute("SELECT count(*) FROM clean_event_base WHERE report_key IS NULL OR report_key = ''").fetchone()[0] == 0
    # R1 appears 3 times in raw (2 in one file, 1 in another) and must survive exactly once
    assert con.execute("SELECT count(*) FROM clean_event_base WHERE report_key = 'R1'").fetchone()[0] == 1


def test_multi_device_report_yields_one_row_per_in_scope_code(tmp_path):
    con = _clean_con(tmp_path)
    codes = sorted(r[0] for r in con.execute("SELECT product_code FROM clean_event_base WHERE report_key='R2'").fetchall())
    assert codes == ["AAA", "BBB"]


def test_received_dates_in_range(tmp_path):
    con = _clean_con(tmp_path)
    lo, hi = con.execute("SELECT min(date_received), max(date_received) FROM clean_event_base").fetchone()
    assert lo >= date(2015, 1, 1) and hi <= date.today()
    kept = {r[0] for r in con.execute("SELECT report_key FROM clean_event_base").fetchall()}
    assert not {"R5", "R6", "R7"} & kept             # future, unparseable, before start


def test_impossible_event_dates_are_nulled_not_dropped(tmp_path):
    con = _clean_con(tmp_path)
    rows = dict(con.execute("SELECT report_key, date_of_event FROM clean_event_base WHERE report_key IN ('R8','R9')").fetchall())
    assert rows == {"R8": None, "R9": None}
    assert con.execute("SELECT count(*) FROM clean_event_base WHERE event_date_invalid").fetchone()[0] == 2


def test_only_in_scope_product_codes(tmp_path):
    con = _clean_con(tmp_path)
    codes = {r[0] for r in con.execute("SELECT DISTINCT product_code FROM clean_event_base").fetchall()}
    valid = {r[0] for r in con.execute("SELECT product_code FROM scope_code").fetchall()}
    assert codes <= valid and "ZZZ" not in codes


def test_problem_vocabulary_is_valid(tmp_path):
    con = _clean_con(tmp_path)
    bad = con.execute("SELECT count(*) FROM event_problem WHERE problem IS NULL OR trim(problem) = ''").fetchone()[0]
    assert bad == 0
    # every problem row belongs to a clean report
    orphans = con.execute("""SELECT count(*) FROM event_problem p
                         LEFT JOIN clean_event_base e USING (report_key, product_code)
                         WHERE e.report_key IS NULL""").fetchone()[0]
    assert orphans == 0
    # missing problem terms are explicit, and case/whitespace variants collapse
    assert con.execute("SELECT problem FROM event_problem WHERE report_key='R3'").fetchone()[0] == "NO PROBLEM REPORTED"
    assert con.execute("SELECT problem FROM event_problem WHERE report_key='R10'").fetchone()[0] == "LEAK"


def test_recall_rows_collapse_to_events(tmp_path):
    recalls = [
        recall("E1", "AAA", "Acme Corp.", "2019-06-01", product_res="Z-1"),
        recall("E1", "AAA", "Acme Corp.", "2019-06-01", product_res="Z-2"),   # same event, second product
        recall("E2", "AAA", "Acme Corp.", "2019-09-01", product_res="Z-3"),
        recall("E3", "ZZZ", "Acme Corp.", "2019-09-01", product_res="Z-4"),   # out of scope
    ]
    con = run_pipeline(tmp_path, {"AAA/a": [event("R1", "20200105", "Acme Corp.")]}, recalls, until="firms")
    got = sorted(con.execute("SELECT res_event_number, n_product_rows FROM clean_recall_base").fetchall())
    assert got == [("E1", 2), ("E2", 1)]


def test_firm_normalisation_and_clustering():
    import duckdb
    import build
    from helpers import CFG, ROOT
    con = duckdb.connect()
    build.setup(con, CFG)   # macros read the params table
    con.execute((ROOT / "sql" / "00_macros.sql").read_text(encoding="utf-8"))
    assert con.execute("SELECT norm_firm('Acme Corp.')").fetchone()[0] == "ACME"
    assert con.execute("SELECT norm_firm('ACME, INCORPORATED')").fetchone()[0] == "ACME"

    mapping = firms.cluster([
        ("MEDTRONIC PUERTO RICO OPERATIONS", 5000), ("MEDTRONIC MINIMED", 3000), ("MEDTRONIC", 100),
        ("INSULET", 4000), ("INSULETT", 10),                       # spelling variant
        ("BAXTER HEALTHCARE", 900), ("BAXTER", 50),
        ("GENERAL ELECTRIC", 80), ("GENERAL MOTORS", 70),          # generic first token must NOT merge
    ])
    assert mapping["MEDTRONIC MINIMED"] == mapping["MEDTRONIC PUERTO RICO OPERATIONS"] == mapping["MEDTRONIC"] == "MEDTRONIC"
    assert mapping["INSULETT"] == mapping["INSULET"]
    assert mapping["BAXTER HEALTHCARE"] == mapping["BAXTER"] == "BAXTER"
    assert mapping["GENERAL ELECTRIC"] != mapping["GENERAL MOTORS"]
