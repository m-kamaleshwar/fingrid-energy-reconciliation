"""Version 1.1: load raw Fingrid API data into Snowflake.

The data is loaded exactly as received (ELT): all transformation happens
inside the warehouse. Loads are idempotent by period: the period is deleted
first, so rerunning never creates duplicates.

Run:  python load_to_snowflake.py --start 2026-10-06T00:00:00Z --end 2026-10-10T00:00:00Z
"""
import os
import time

import pandas as pd
import snowflake.connector as con
from snowflake.connector.pandas_tools import write_pandas

from fingrid_api import fetch_all_datasets, parse_period

WAREHOUSE = "COMPUTE_WH"
DATABASE = "STG_FIN_GRID"
SCHEMA = "RAW"
TABLE = "FINGRID_READINGS"


def get_connection():
    """Connect using credentials from environment variables."""
    needed = ["SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ACCOUNT"]
    missing = [v for v in needed if not os.getenv(v)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    return con.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=WAREHOUSE,
        database=DATABASE,
        schema=SCHEMA,
    )


def main():
    start, end = parse_period("Load raw Fingrid data into Snowflake.")
    started = time.time()

    raw = fetch_all_datasets(start, end)
    df = pd.concat(raw.values(), ignore_index=True).rename(columns={
        "datasetId": "dataset_id", "startTime": "start_time", "endTime": "end_time"})

    # Keep only rows inside the period, so the delete step always covers them.
    in_period = (df["start_time"] >= pd.Timestamp(start)) & (df["start_time"] < pd.Timestamp(end))
    if (~in_period).any():
        print(f"\n  Note: {(~in_period).sum()} rows outside the period were skipped")
    df = df[in_period].copy()
    df["loaded_at"] = pd.Timestamp.now(tz="UTC")

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
                            DATASET_ID INTEGER,
                            START_TIME TIMESTAMP_TZ,
                            END_TIME   TIMESTAMP_TZ,
                            VALUE      FLOAT,
                            LOADED_AT  TIMESTAMP_TZ)""")

        # Idempotent: replace the whole period rather than adding to it.
        cur.execute(f"DELETE FROM {TABLE} WHERE START_TIME >= %s AND START_TIME < %s",
                    (start, end))
        write_pandas(conn, df, TABLE, quote_identifiers=False, use_logical_type=True)

        # Reconcile the load: Snowflake must hold exactly what was fetched.
        cur.execute(f"""SELECT DATASET_ID, COUNT(*) FROM {TABLE}
                        WHERE START_TIME >= %s AND START_TIME < %s
                        GROUP BY DATASET_ID""", (start, end))
        loaded = {int(k): int(v) for k, v in cur.fetchall()}
        expected = {int(k): int(v) for k, v in df.groupby("dataset_id").size().items()}

        print("\nLoad check (dataset: fetched / in Snowflake):")
        for dataset_id in sorted(expected):
            print(f"  {dataset_id}: {expected[dataset_id]} / {loaded.get(dataset_id, 0)}")
        if loaded != expected:
            raise RuntimeError("Row counts in Snowflake don't match what was fetched.")
        print(f"\nLoaded {len(df)} rows into {DATABASE}.{SCHEMA}.{TABLE} for {start} to {end}.")
    finally:
        conn.close()

    minutes, seconds = divmod(time.time() - started, 60)
    print(f"Completed in {int(minutes)} minutes and {seconds:.2f} seconds.")


if __name__ == "__main__":
    main()
