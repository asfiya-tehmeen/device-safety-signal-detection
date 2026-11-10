"""Manufacturer name harmonisation (MAUDE manufacturer names and recalling-firm names).

Method (parent-level grouping, documented as a limitation):
  1. norm_firm() in SQL strips punctuation and legal suffixes.
  2. Names sharing a distinctive first token (>= 5 chars, not a generic word) are grouped
     (e.g. MEDTRONIC PUERTO RICO OPERATIONS + MEDTRONIC MINIMED -> MEDTRONIC).
  3. Remaining names are merged with near-identical ones (rapidfuzz ratio >= 92, catches spelling variants).
  4. config/firm_overrides.csv (firm_norm,firm_std) is applied last, from manual review of the top 50.

Outputs (both committed, so the mapping is auditable):
  data/clean/firm_map.csv            every firm_norm -> firm_std
  reports/firm_review_top50.csv      top 50 groups with member names, for manual review
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import duckdb
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "data" / "clean" / "firm_map.csv"
REVIEW_PATH = ROOT / "reports" / "firm_review_top50.csv"
OVERRIDES_PATH = ROOT / "config" / "firm_overrides.csv"

# First tokens too generic to identify a company on their own.
GENERIC_FIRST = {
    "AMERICAN", "GENERAL", "UNITED", "INTERNATIONAL", "NATIONAL", "GLOBAL", "ADVANCED", "PRECISION",
    "UNIVERSAL", "MEDICAL", "HEALTH", "HEALTHCARE", "SURGICAL", "TECHNOLOGIES", "TECHNOLOGY", "SYSTEMS",
    "CARDIO", "DIAGNOSTIC", "DIAGNOSTICS", "BIO", "LIFE", "CARE", "PHARMA", "SCIENTIFIC", "ELECTRONICS",
    "CHINA", "SHENZHEN", "SHANGHAI", "BEIJING", "GUANGDONG", "JIANGSU", "ZHEJIANG", "SOUTH", "NORTH",
    "EAST", "WEST", "FIRST", "CENTRAL", "PACIFIC", "ATLANTIC", "DIGITAL", "DYNAMIC", "SMART", "NEW",
}


def _first(name: str) -> str:
    return name.split()[0] if name else ""


def _qualifies(tok: str) -> bool:
    return len(tok) >= 5 and tok not in GENERIC_FIRST


def cluster(names: list[tuple[str, int]]) -> dict[str, str]:
    """names: (firm_norm, weight). Returns firm_norm -> firm_std."""
    group_members: dict[str, list[str]] = defaultdict(list)
    weight = dict(names)
    for name, _ in names:
        key = _first(name) if _qualifies(_first(name)) else name
        group_members[key].append(name)
    # std name: the first token if the group merges several names, else the name itself
    std_of_group = {k: (k if len(v) > 1 else v[0]) for k, v in group_members.items()}
    group_weight = {k: sum(weight[n] for n in v) for k, v in group_members.items()}

    # fuzzy merge of remaining groups into heavier ones (spelling variants only)
    heads: list[str] = []
    merged_into: dict[str, str] = {}
    for g in sorted(group_members, key=lambda k: -group_weight[k]):
        std = std_of_group[g]
        hit = process.extractOne(std, heads, scorer=fuzz.ratio, score_cutoff=92) if heads else None
        if hit:
            merged_into[g] = hit[0]
        else:
            heads.append(std)
            merged_into[g] = std
    out = {}
    for g, members in group_members.items():
        for n in members:
            out[n] = merged_into[g]
    return out


def build_firm_map(con: duckdb.DuckDBPyConnection) -> None:
    rows = con.sql("""
        SELECT firm_norm, sum(w)::BIGINT FROM (
            SELECT firm_norm, count(*) AS w FROM clean_event_base GROUP BY 1
            UNION ALL
            SELECT firm_norm, 50 * count(*) FROM clean_recall_base GROUP BY 1)   -- recall names must be mapped too
        WHERE firm_norm <> '' GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    names = [(r[0], int(r[1])) for r in rows]
    mapping = cluster(names)

    if OVERRIDES_PATH.exists():
        with OVERRIDES_PATH.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("firm_norm") and r.get("firm_std"):
                    mapping[r["firm_norm"].strip()] = r["firm_std"].strip()

    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MAP_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["firm_norm", "firm_std"])
        for n, _ in names:
            w.writerow([n, mapping[n]])

    con.execute(
        "CREATE OR REPLACE TABLE firm_map AS "
        "SELECT firm_norm, firm_std FROM read_csv(?, header = true, all_varchar = true)",
        [str(MAP_PATH)],
    )

    # top-50 review file
    weight = dict(names)
    members: dict[str, list[str]] = defaultdict(list)
    for n, std in mapping.items():
        members[std].append(n)
    ranked = sorted(members.items(), key=lambda kv: -sum(weight.get(n, 0) for n in kv[1]))[:50]
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "firm_std", "weight", "n_names", "member_names (top 8 by weight)"])
        for i, (std, ms) in enumerate(ranked, 1):
            ms_sorted = sorted(ms, key=lambda n: -weight.get(n, 0))
            w.writerow([i, std, sum(weight.get(n, 0) for n in ms), len(ms), " | ".join(ms_sorted[:8])])
