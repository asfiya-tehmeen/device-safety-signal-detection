"""Signal tests: PRR/ROR vs hand-worked 2x2 tables, small-count rules, trend, and the as-of (no future data) guarantee."""
import math
import random
from datetime import date

import pytest
from scipy.stats import poisson

from helpers import event, run_pipeline

Z = 1.96


def _row(con, firm, problem, month, table="signal_stats"):
    return con.execute(
        f"SELECT * FROM {table} WHERE firm = ? AND problem = ? AND M = ? AND product_code = 'AAA'",
        [firm, problem, month]).fetchdf().iloc[0]


def test_prr_ror_match_hand_worked_2x2(tmp_path):
    # Month 2017-06, product code AAA.
    #   firm FIRMF: 100 reports, 10 with problem X          -> a=10, b=90
    #   all other firms: 900 reports, 20 with problem X     -> c=20, d=880
    rows, n = [], 0
    for firm, total, with_x in [("FIRMF", 100, 10), ("FIRMG", 900, 20)]:
        for i in range(total):
            rows.append(event(f"R{n}", "20170615", firm, problems=("X",) if i < with_x else ("Y",)))
            n += 1
    con = run_pipeline(tmp_path, {"AAA/a": rows}, until="signals")
    r = _row(con, "FIRMF", "X", date(2017, 6, 1))

    assert (r.a, r.b, r.c, r.d) == (10, 90, 20, 880)
    assert not r.corrected
    prr = (10 / 100) / (20 / 900)                                   # 4.5
    ror = (10 * 880) / (90 * 20)                                    # 4.888...
    se_prr = math.sqrt(1/10 - 1/100 + 1/20 - 1/900)
    se_ror = math.sqrt(1/10 + 1/90 + 1/20 + 1/880)
    assert r.prr == pytest.approx(prr)
    assert r.ror == pytest.approx(ror)
    assert r.prr_lcl == pytest.approx(math.exp(math.log(prr) - Z * se_prr))
    assert r.prr_ucl == pytest.approx(math.exp(math.log(prr) + Z * se_prr))
    assert r.ror_lcl == pytest.approx(math.exp(math.log(ror) - Z * se_ror))
    assert r.ror_ucl == pytest.approx(math.exp(math.log(ror) + Z * se_ror))
    # sanity: PRR = 4.5 is reported as exactly that
    assert r.prr == pytest.approx(4.5)


def test_zero_cell_gets_haldane_correction_and_finite_estimates(tmp_path):
    # FIRMF reports only X, FIRMG only Y -> for (FIRMF, X): b=0 and c=0
    rows = [event(f"F{i}", "20170610", "FIRMF", problems=("X",)) for i in range(5)]
    rows += [event(f"G{i}", "20170611", "FIRMG", problems=("Y",)) for i in range(5)]
    con = run_pipeline(tmp_path, {"AAA/a": rows}, until="signals")
    r = _row(con, "FIRMF", "X", date(2017, 6, 1))
    assert r.corrected
    assert (r.a, r.b, r.c, r.d) == (5, 0, 0, 5)                    # reported counts stay raw
    assert r.prr == pytest.approx((5.5 / 6.0) / (0.5 / 6.0))       # +0.5 to every cell -> 11
    assert math.isfinite(r.prr_lcl) and math.isfinite(r.ror_ucl)


def test_minimum_count_rule(tmp_path):
    rows = [event(f"F{i}", "20170610", "FIRMF", problems=("X",)) for i in range(2)]      # a = 2 < 3
    rows += [event(f"F{i+9}", "20170610", "FIRMF", problems=("Z",)) for i in range(3)]   # a = 3 -> allowed
    rows += [event(f"G{i}", "20170611", "FIRMG", problems=("Y",)) for i in range(20)]
    con = run_pipeline(tmp_path, {"AAA/a": rows}, until="signals")
    assert con.execute("SELECT count(*) FROM signal_stats WHERE a < 3").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM signal_stats WHERE firm='FIRMF' AND problem='X'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM signal_stats WHERE firm='FIRMF' AND problem='Z'").fetchone()[0] == 1


def test_generic_problem_terms_are_not_screened(tmp_path):
    rows = [event(f"F{i}", "20170610", "FIRMF", problems=("Insufficient Information",)) for i in range(6)]
    rows += [event(f"G{i}", "20170611", "FIRMG", problems=("Y",)) for i in range(20)]
    con = run_pipeline(tmp_path, {"AAA/a": rows}, until="signals")
    assert con.execute("SELECT count(*) FROM signal_stats WHERE problem = 'INSUFFICIENT INFORMATION'").fetchone()[0] == 0


def test_trend_counts_and_poisson_p(tmp_path):
    # FIRMF reports X once a month for 12 months (2016-04..2017-03), then 6 a month for 2017-04..06.
    rows, n = [], 0
    for y, m in [(2016, mm) for mm in range(4, 13)] + [(2017, mm) for mm in range(1, 4)]:
        rows.append(event(f"B{n}", f"{y}{m:02d}10", "FIRMF", problems=("X",))); n += 1
    for m in (4, 5, 6):
        for _ in range(6):
            rows.append(event(f"S{n}", f"2017{m:02d}10", "FIRMF", problems=("X",))); n += 1
    for y, m in [(2016, mm) for mm in range(1, 13)] + [(2017, mm) for mm in range(1, 7)]:     # background firm
        for _ in range(20):
            rows.append(event(f"G{n}", f"{y}{m:02d}12", "FIRMG", problems=("Y",))); n += 1
    con = run_pipeline(tmp_path, {"AAA/a": rows}, until="signals")
    r = _row(con, "FIRMF", "X", date(2017, 6, 1))
    assert (r.k3, r.base12) == (18, 12)
    assert r.exp_k3 == pytest.approx((12 + 0.5) * 3 / 12)
    assert r.trend_p == pytest.approx(poisson.sf(18 - 1, (12 + 0.5) * 3 / 12))
    assert r.trend_p < 1e-6


def test_poisson_udf_edge_cases():
    import build
    assert build.poisson_sf(0, 2.0) == pytest.approx(1.0)
    assert build.poisson_sf(5, 2.0) == pytest.approx(poisson.sf(4, 2.0))
    assert build.poisson_sf(None, 2.0) is None


# ---------------------------------------------------------------------------------------------------
# As-of guarantee
# ---------------------------------------------------------------------------------------------------
def _synthetic(seed=7, months=36):
    rng = random.Random(seed)
    firms = ["ALPHA", "BRAVO", "CHARLIE", "DELTA"]
    problems = ["P1", "P2", "P3", "P4", "P5"]
    rows, n = [], 0
    for mi in range(months):
        y, m0 = divmod(2016 * 12 + mi, 12)
        for firm in firms:
            for _ in range(rng.randint(25, 45)):
                probs = rng.sample(problems, rng.choice([1, 2]))
                if firm == "BRAVO" and mi >= 24 and rng.random() < 0.5:     # an emerging problem late in the series
                    probs = ["P1"]
                rows.append(event(f"S{n}", f"{y}{m0 + 1:02d}{rng.randint(1, 28):02d}", firm, problems=probs))
                n += 1
    return rows


def _fetch(con, table, cut):
    cols = [c[0] for c in con.execute(f"DESCRIBE {table}").fetchall()]
    order = ", ".join(c for c in cols if c in ("product_code", "firm", "problem", "M"))
    return con.execute(f"SELECT * FROM {table} WHERE M <= ? ORDER BY {order}", [cut]).fetchall()


def test_signals_use_no_data_received_after_the_month_being_scored(tmp_path):
    rows = _synthetic()
    cut_month, cut_prefix = date(2018, 3, 1), "201803"          # month 27 of 36 (BRAVO's emerging problem is under way)
    truncated = [r for r in rows if r["date_received"][:6] <= cut_prefix]
    assert 0 < len(truncated) < len(rows)

    full = run_pipeline(tmp_path / "full", {"AAA/a": rows}, until="baseline")
    trunc = run_pipeline(tmp_path / "trunc", {"AAA/a": truncated}, until="baseline")

    # every statistic, for every as-of month up to the cut, is identical with or without the future
    for table in ("signal_stats", "baseline_fire"):
        a, b = _fetch(full, table, cut_month), _fetch(trunc, table, cut_month)
        assert len(a) > 0, f"{table}: test would be vacuous"
        assert a == b, f"{table} differs when future reports are removed"

    # and the test has teeth: the full run really did see later months
    assert full.execute("SELECT max(M) FROM signal_stats").fetchone()[0] > cut_month
    assert trunc.execute("SELECT max(M) FROM signal_stats").fetchone()[0] <= cut_month
    # the emerging problem is detected as of the cut month in both runs
    fired = trunc.execute("SELECT count(*) FROM signal WHERE firm='BRAVO' AND problem='P1' AND fire_sensitive").fetchone()[0]
    assert fired > 0


def test_benjamini_hochberg_matches_statsmodels(tmp_path):
    from statsmodels.stats.multitest import multipletests
    con = run_pipeline(tmp_path, {"AAA/a": _synthetic()}, until="signals")
    for month in con.execute("SELECT DISTINCT M FROM signal ORDER BY M").fetchall()[::7]:
        d = con.execute("SELECT trend_p, trend_q FROM signal WHERE M = ? ORDER BY trend_p", [month[0]]).fetchdf()
        expected = multipletests(d.trend_p, method="fdr_bh")[1]
        assert d.trend_q.to_numpy() == pytest.approx(expected)
