"""openFDA ingest: MAUDE events, recalls, classification. Resumable, cached, rate-limited.

Raw layout (never edited):
  data/raw/event/<CODE>/<start>_<end>.jsonl.gz   one file per date_received window
  data/raw/recall/<CODE>.jsonl.gz
  data/raw/classification.jsonl.gz

Set OPENFDA_API_KEY (free: https://open.fda.gov/apis/authentication/). Without a key openFDA allows
only ~1,000 requests/day per IP, which is not enough for the full-record pull.
"""
from __future__ import annotations

import argparse
import calendar
import gzip
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = "https://api.fda.gov/device/"
PAGE = 1000          # openFDA max limit per call
SKIP_CAP = 25000     # openFDA max skip; windows with more records are split
MIN_INTERVAL = 0.3   # seconds between calls (keeps well under 240/min)

log = logging.getLogger("ingest")
_session = requests.Session()
_last_call = 0.0


class OpenFDAError(RuntimeError):
    pass


def _get(endpoint: str, params: dict, retries: int = 6) -> dict:
    """GET with throttle, API key, retry on 429/5xx. Returns {} for 404 (= no matches)."""
    global _last_call
    key = os.environ.get("OPENFDA_API_KEY")
    if key:
        params = {**params, "api_key": key}
    for attempt in range(retries):
        wait = MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            r = _session.get(BASE + endpoint + ".json", params=params, timeout=90)
        except requests.RequestException as e:
            log.warning("network error %s (attempt %d)", e, attempt + 1)
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return {}
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            delay = min(60, 2 ** attempt * 2)
            log.warning("HTTP %s, sleeping %ss", r.status_code, delay)
            time.sleep(delay)
            continue
        raise OpenFDAError(f"HTTP {r.status_code}: {r.text[:300]}")
    raise OpenFDAError(f"gave up after {retries} attempts: {endpoint} {params}")


def _total(endpoint: str, search: str) -> int:
    d = _get(endpoint, {"search": search, "limit": 1})
    return d.get("meta", {}).get("results", {}).get("total", 0) if d else 0


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    tmp.replace(path)  # atomic: a partial file is never mistaken for a finished window


def _fetch_all(endpoint: str, search: str, total: int) -> list[dict]:
    out: list[dict] = []
    for skip in range(0, total, PAGE):
        d = _get(endpoint, {"search": search, "limit": PAGE, "skip": skip})
        out.extend(d.get("results", []))
    return out


def _windows_month(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        last = calendar.monthrange(y, m)[1]
        yield date(y, m, 1), min(date(y, m, last), end)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def _event_search(code: str, a: date, b: date) -> str:
    return (f"device.device_report_product_code:{code} AND "
            f"date_received:[{a:%Y%m%d} TO {b:%Y%m%d}]")


def ingest_window(code: str, a: date, b: date, refresh: bool = False) -> int:
    """Fetch one date_received window, splitting in halves if it exceeds the skip cap.

    Returns number of reports fetched, or -1 if the window was already cached.
    """
    path = RAW / "event" / code / f"{a:%Y%m%d}_{b:%Y%m%d}.jsonl.gz"
    if path.exists() and not refresh:
        return -1
    search = _event_search(code, a, b)
    total = _total("event", search)
    if total == 0:
        _write(path, [])
        return 0
    if total > SKIP_CAP and a < b:
        mid = a + (b - a) // 2
        n = max(ingest_window(code, a, mid, refresh), 0) + max(
            ingest_window(code, mid + timedelta(days=1), b, refresh), 0)
        _write(path, [])  # parent is a marker; the children hold the data
        path.with_suffix(".split").write_text("split")
        return n
    if total > SKIP_CAP:
        log.error("single day %s %s has %d > cap; records beyond %d are NOT retrieved",
                  code, a, total, SKIP_CAP)
        total = SKIP_CAP
    recs = _fetch_all("event", search, total)
    _write(path, recs)
    return len(recs)


def ingest_events(codes: list[str], start: date, end: date, refresh_last_months: int = 2) -> None:
    today = date.today()
    for code in codes:
        n_total = 0
        for a, b in _windows_month(start, end):
            # recent months are still updated weekly by FDA: always refresh them
            recent = (today.year - a.year) * 12 + today.month - a.month < refresh_last_months
            n = ingest_window(code, a, b, refresh=recent)
            if n > 0:
                n_total += n
                log.info("%s %s: %d reports", code, f"{a:%Y-%m}", n)
        log.info("== %s done, %d new reports", code, n_total)


def ingest_recalls(codes: list[str]) -> None:
    for code in codes:
        search = f"product_code:{code}"
        total = _total("recall", search)
        recs = _fetch_all("recall", search, min(total, SKIP_CAP)) if total else []
        _write(RAW / "recall" / f"{code}.jsonl.gz", recs)
        log.info("recalls %s: %d", code, len(recs))


def ingest_classification(codes: list[str]) -> None:
    recs = []
    for code in codes:
        d = _get("classification", {"search": f"product_code:{code}", "limit": 5})
        recs.extend(d.get("results", []) if d else [])
    _write(RAW / "classification.jsonl.gz", recs)
    log.info("classification: %d records", len(recs))


def load_scope() -> dict:
    return yaml.safe_load((ROOT / "config" / "scope.yaml").read_text(encoding="utf-8"))


def scope_codes(scope: dict) -> list[str]:
    return [c for group in scope["areas"].values() for c in group]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["classification", "recalls", "events", "all"])
    ap.add_argument("--codes", nargs="*", help="override product codes")
    ap.add_argument("--start", help="YYYY-MM-DD (default: scope.yaml)")
    ap.add_argument("--end", help="YYYY-MM-DD (default: today)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    scope = load_scope()
    all_codes = scope_codes(scope)
    codes = args.codes or all_codes
    start = datetime.strptime(args.start or scope["date_range"]["start"], "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()

    if args.what in ("classification", "all"):
        ingest_classification(all_codes)
    if args.what in ("recalls", "all"):
        ingest_recalls(codes)
    if args.what in ("events", "all"):
        ingest_events(codes, start, end)


if __name__ == "__main__":
    main()
