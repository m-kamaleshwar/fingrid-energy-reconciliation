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
PAGE_SIZE = 1000
REQUEST_PAUSE_SECONDS = 2  # Fingrid allows one request every 2 seconds

# Fingrid returns at most 2,000 rows per query, newest first, and reports the
# capped number as its total. Longer periods therefore lose their OLDEST rows
# silently. Fetching in chunks keeps every query safely under the cap:
# 3 days of 3-minute data is at most 1,440 rows.
API_ROW_CAP = 2000
CHUNK_DAYS = 3

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
    page = 1
    while True:
        resp = requests.get(url, headers=headers,
                            params={**params, "page": page}, timeout=30)
        resp.raise_for_status()  # fail loudly on errors such as 401 or 429
        data = resp.json()
        all_rows.extend(data["data"])

        pagination = data.get("pagination", {})
        if page >= pagination.get("lastPage", 1):
            break
        page += 1
        time.sleep(REQUEST_PAUSE_SECONDS)

    # Reconcile against the source: the API reports how many rows exist.
    total = data.get("pagination", {}).get("total")
    if total is not None and len(all_rows) != total:
        raise RuntimeError(
            f"Dataset {dataset_id}: fetched {len(all_rows)} rows, "
            f"but the API reports {total}")

    # The total check can't catch the cap, because the API reports the capped
    # total. A window that reaches the cap may be missing its oldest rows.
    if len(all_rows) >= API_ROW_CAP:
        raise RuntimeError(
            f"Dataset {dataset_id}: {len(all_rows)} rows for {start} to {end} "
            f"reached the API's {API_ROW_CAP}-row cap, so older rows may be missing. "
            f"Reduce CHUNK_DAYS.")

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