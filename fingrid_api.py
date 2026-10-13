"""Shared helpers for calling Fingrid's open data API.

Used by reconcile_pandas.py and load_to_snowflake.py, so the fetching
logic exists in one place only.
"""
import argparse
import os
import time
import warnings

import pandas as pd
import requests

# pandas and NumPy versions currently emit this harmless notice internally.
warnings.filterwarnings(
    "ignore",
    message=r".*'generic' unit for NumPy timedelta is deprecated.*",
    category=DeprecationWarning,
)

BASE_URL = "https://data.fingrid.fi/api/datasets/{}/data"
PAGE_SIZE = 20000           # Fingrid's maximum rows per page
REQUEST_PAUSE_SECONDS = 2  # Fingrid allows one request every 2 seconds

# Testing showed that when a query has more than two pages, the API's paging
# information is wrong: it reports only two pages, and a total covering only
# those, although later pages still return data. Code that trusts it silently
# loses the OLDEST rows (pageSize 1,000 gave 2,000 of 2,173 rows for five days,
# and page 3 held the other 173). So pages are requested until a short page
# comes back, and the reported total is treated only as a minimum. Chunks keep
# each query to a single page anyway: 30 days of 3-minute data is at most
# 14,400 rows, well under 20,000.
CHUNK_DAYS = 30

# Default period, in UTC. Override with --start and --end on the command line.
DEFAULT_START = "2026-10-06T00:00:00Z"
DEFAULT_END = "2026-10-10T00:00:00Z"

# Datasets used in the project. Browse them at https://data.fingrid.fi/en/datasets
DATASETS = [
    {"name": "production",       "dataset_id": 192, "interval": 3},
    {"name": "consumption",      "dataset_id": 193, "interval": 3},
    {"name": "north_swed",       "dataset_id": 87,  "interval": 3},
    {"name": "cent_swed",        "dataset_id": 89,  "interval": 3},
    {"name": "estonia",          "dataset_id": 180, "interval": 3},
    {"name": "norway",           "dataset_id": 187, "interval": 3},
    {"name": "prod_measurement", "dataset_id": 74,  "interval": 15},
    {"name": "cons_measurement", "dataset_id": 124, "interval": 15},
]


def get_headers():
    """Read the API key from the environment, never from code."""
    api_key = os.getenv("FINGRID_API_KEY")
    if not api_key:
        raise ValueError("FINGRID_API_KEY environment variable is not set.")
    return {"x-api-key": api_key}


def _fetch_window(dataset_id, start, end, headers):
    """Fetch every page of one dataset for one window, and check nothing was missed."""
    url = BASE_URL.format(dataset_id)
    params = {"startTime": start, "endTime": end, "pageSize": PAGE_SIZE}

    all_rows = []
    reported_total = None
    page = 1
    while True:
        resp = requests.get(url, headers=headers,
                            params={**params, "page": page}, timeout=30)
        resp.raise_for_status()  # fail loudly on errors such as 401 or 429
        data = resp.json()
        rows = data["data"]
        all_rows.extend(rows)
        if reported_total is None:
            reported_total = data.get("pagination", {}).get("total")

        # Don't trust the reported page count: a short (or empty) page is the last.
        if len(rows) < PAGE_SIZE:
            break
        page += 1
        time.sleep(REQUEST_PAUSE_SECONDS)

    # The reported total can be too LOW, but never too high: fewer rows than
    # reported means something was genuinely lost.
    if reported_total is not None and len(all_rows) < reported_total:
        raise RuntimeError(
            f"Dataset {dataset_id}: fetched {len(all_rows)} rows for {start} to {end}, "
            f"but the API reports at least {reported_total}")

    df = pd.DataFrame(all_rows, columns=["datasetId", "startTime", "endTime", "value"])
    df["startTime"] = pd.to_datetime(df["startTime"])
    df["endTime"] = pd.to_datetime(df["endTime"])
    return df


def _iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_dataset(dataset_id, start, end, headers):
    """Fetch one dataset for any period, in chunks that stay under the API cap."""
    period_start, period_end = pd.Timestamp(start), pd.Timestamp(end)
    parts = []
    chunk_start = period_start
    while chunk_start < period_end:
        chunk_end = min(chunk_start + pd.Timedelta(days=CHUNK_DAYS), period_end)
        if parts:
            time.sleep(REQUEST_PAUSE_SECONDS)
        parts.append(_fetch_window(dataset_id, _iso(chunk_start), _iso(chunk_end), headers))
        chunk_start = chunk_end

    df = pd.concat(parts, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates(subset=["datasetId", "startTime", "endTime"]).reset_index(drop=True)
    if len(df) < before:
        print(f"  Note: {before - len(df)} duplicate rows at chunk boundaries removed")
    return df


def fetch_all_datasets(start, end):
    """Fetch every dataset in DATASETS. Returns {name: raw DataFrame}."""
    headers = get_headers()
    raw = {}
    for i, ds in enumerate(DATASETS):
        if i:
            time.sleep(REQUEST_PAUSE_SECONDS)
        print(f"\nFetching {ds['name']} (dataset {ds['dataset_id']}, "
              f"{ds['interval']}-minute)...")
        df = fetch_dataset(ds["dataset_id"], start, end, headers)
        print(f"  Records fetched: {len(df)}")
        raw[ds["name"]] = df
    return raw


def parse_period(description):
    """Read --start and --end from the command line, with sensible defaults."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--start", default=DEFAULT_START,
                        help="Period start in UTC, e.g. 2026-10-06T00:00:00Z")
    parser.add_argument("--end", default=DEFAULT_END,
                        help="Period end in UTC (exclusive), e.g. 2026-10-10T00:00:00Z")
    args = parser.parse_args()
    return args.start, args.end
