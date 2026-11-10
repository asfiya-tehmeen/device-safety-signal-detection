"""Backtest tests on a deterministic scenario.

Background (no disproportionality by construction): every firm reports the same 50/50 mix of two problems each month,
2016-01 .. 2021-06. On top of that:
  FIRMF  spike of problem X   2018-07..2018-09, 8 extra reports a month        recalled 2019-01-15 (E1)  -> true alert
  FIRMH  spike of problem X2  2018-02..2018-04, 8 extra reports a month        never recalled            -> false alarm
  FIRMG  no spike                                                              recalled 2019-03-01 (E2)  -> not flagged
  FIRMF  recall E3 on 2018-05-01 is BEFORE its spike                                                     -> must not count
"""
from datetime import date

import pytest

from helpers import ROOT, event, recall, run_pipeline


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    rows, n = [], 0

    def add(firm, y, m, problems):
        nonlocal n
        rows.append(event(f"R{n}", f"{y}{m:02d}15", firm, problems=problems))
        n += 1

    months = [(y, m) for y in range(2016, 2022) for m in range(1, 13) if (y, m) <= (2021, 6)]
    for y, m in months:
        for firm, per in (("FIRMF", 4), ("FIRMH", 4), ("FIRMG", 20)):
            for _ in range(per):
                add(firm, y, m, ("B1",))
                add(firm, y, m, ("B2",))
    for y, m in [(2018, 7), (2018, 8), (2018, 9)]:
        for _ in range(8):
            add("FIRMF", y, m, ("X",))
    for y, m in [(2018, 2), (2018, 3), (2018, 4)]:
        for _ in range(8):
            add("FIRMH", y, m, ("X2",))

    recalls = [
        recall("E1", "AAA", "FirmF Inc.", "2019-01-15"),    # name differs from MAUDE spelling: join uses norm_firm
        recall("E2", "AAA", "FIRMG", "2019-03-01"),
        recall("E3", "AAA", "FIRMF", "2018-05-01"),
    ]
    return run_pipeline(tmp_path_factory.mktemp("bt"), {"AAA/a": rows}, recalls, until="null")


def test_spike_fires_and_background_does_not(con):
    fired = {(r[0], r[1]) for r in con.execute(
        "SELECT firm, problem FROM signal WHERE fire_sensitive").fetchall()}
    assert ("FIRMF", "X") in fired and ("FIRMH", "X2") in fired
    assert not any(p in ("B1", "B2") for _, p in fired)            # steady 50/50 background never signals


def test_recall_flagged_in_advance_with_correct_lead(con):
    r = con.execute("""SELECT first_fire_month, first_alert_end, recall_date, lead_months FROM recall_eval
                       WHERE method = 'prr_sensitive' AND res_event_number = 'E1'""").fetchone()
    first_fire, alert_end, recall_date, lead = r
    assert first_fire == date(2018, 7, 1)                          # first month the spike enters the data
    assert alert_end == date(2018, 7, 31) and alert_end < recall_date
    assert lead == pytest.approx((date(2019, 1, 15) - date(2018, 7, 31)).days / 30.4375)
    assert 5.5 < lead < 6.0


def test_unrelated_and_pre_spike_recalls_are_not_flagged(con):
    rows = dict(con.execute("""SELECT res_event_number, first_fire_month FROM recall_eval
                               WHERE method = 'prr_sensitive'""").fetchall())
    assert rows["E2"] is None                                      # FIRMG never signalled
    assert rows["E3"] is None                                      # FIRMF signalled only AFTER this recall


def test_alert_episodes_and_false_alarm(con):
    alerts = con.execute("""SELECT firm, alert_month, followed_by_recall FROM alert_eval
                            WHERE method = 'prr_sensitive' ORDER BY firm""").fetchall()
    assert alerts == [("FIRMF", date(2018, 7, 1), True), ("FIRMH", date(2018, 2, 1), False)]
    # three consecutive firing months are ONE episode, not three alerts
    n_fire = con.execute("SELECT count(*) FROM fire_month WHERE method='prr_sensitive' AND firm='FIRMF'").fetchone()[0]
    assert n_fire >= 2


def test_evaluation_table_values(con):
    ev = con.execute("""SELECT * FROM evaluation
                        WHERE method = 'prr_sensitive' AND area = 'ALL' AND population = 'eligible'""").fetchdf().iloc[0]
    assert ev.n_recalls == 3 and ev.n_flagged_in_advance == 1
    assert ev.recall_rate == pytest.approx(0.333, abs=1e-3)
    assert ev.n_alerts_matured == 2 and ev.n_true_alerts == 1 and ev.n_false_alerts == 1
    assert ev.precision == pytest.approx(0.5)
    n_months = con.execute("SELECT n_months FROM eval_months").fetchone()[0]
    assert ev.false_alarms_per_month == pytest.approx(round(1 / n_months, 2))


def test_baseline_is_evaluated_on_the_same_footing(con):
    methods = {r[0] for r in con.execute("SELECT DISTINCT method FROM evaluation").fetchall()}
    assert methods == {"prr_sensitive", "prr_strict", "prr_fdr", "baseline_2sd", "any_activity"}
    b = con.execute("""SELECT n_flagged_in_advance FROM evaluation
                       WHERE method='baseline_2sd' AND area='ALL' AND population='eligible'""").fetchone()[0]
    assert b == 1            # a 16-vs-8 jump with zero variance also trips the simple baseline: it is not "worse by default"


def test_only_matured_alerts_are_scored(con):
    # data ends 2021-06; an alert is scored only if its follow-up window (24 months) fits in the data
    latest = con.execute("SELECT max(alert_end) FROM alert_eval").fetchone()[0]
    assert latest <= date(2019, 6, 30)


def test_any_activity_rule_flags_every_active_firm(con):
    # FIRMG reports every month, so the always-on rule "flags" its recall even though nothing changed
    hit = con.execute("""SELECT first_fire_month IS NOT NULL FROM recall_eval
                         WHERE method='any_activity' AND res_event_number='E2'""").fetchone()[0]
    assert hit


def test_null_test_is_deterministic_and_well_formed(con):
    s = con.execute("SELECT * FROM null_summary ORDER BY method").fetchdf()
    assert set(s.method) == {"prr_sensitive", "prr_strict", "prr_fdr", "baseline_2sd", "any_activity"}
    assert ((s.null_mean_rate >= 0) & (s.null_mean_rate <= 1)).all()
    assert ((s.p_value > 0) & (s.p_value <= 1)).all()
    # only recalls with a full look-back (>= 2019-01-01) are in the null population: E1 and E2, not E3
    assert set(s.n_recalls) == {2}
    lo, hi = con.execute("SELECT lo, hi FROM null_bounds").fetchone()
    assert lo == date(2019, 1, 1)
    out = con.execute("SELECT count(*) FROM null_recall WHERE fake_date < ? OR fake_date > ?", [lo, hi]).fetchone()[0]
    assert out == 0
    # same hash -> same dates on a rerun
    con.execute((ROOT / "sql" / "07_null.sql").read_text(encoding="utf-8"))
    assert con.execute("SELECT * FROM null_summary ORDER BY method").fetchdf().equals(s)
    # always-on: any random date for always-active FIRMG is also "flagged" -> no lift over random
    g = con.execute("""SELECT avg(hit::INT) FROM null_recall WHERE method='any_activity' AND firm='FIRMG'""").fetchone()[0]
    assert g == 1.0
