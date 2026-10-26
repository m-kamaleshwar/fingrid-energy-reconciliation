"""Load raw Fingrid API data into a local DuckDB file for dbt development.

Run:  python load_to_duckdb.py --start 2026-10-06T00:00:00Z --end 2026-10-10T00:00:00Z
"""
import duckdb
import pandas as pd

from fingrid_api import fetch_all_datasets, parse_period

DB_FILE = "fingrid.duckdb"


def main():
    start, end = parse_period("Load raw Fingrid data into a local DuckDB file.")
    raw = fetch_all_datasets(start, end)
    df = pd.concat(raw.values(), ignore_index=True).rename(columns={
        "datasetId": "dataset_id", "startTime": "start_time", "endTime": "end_time"})

    # Store all times as UTC without a time zone, so every model works in UTC
    for col in ("start_time", "end_time"):
        df[col] = df[col].dt.tz_convert("UTC").dt.tz_localize(None)
    period_start = pd.Timestamp(start).tz_convert("UTC").tz_localize(None)
    period_end = pd.Timestamp(end).tz_convert("UTC").tz_localize(None)

    con = duckdb.connect(DB_FILE)
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        con.execute("""CREATE TABLE IF NOT EXISTS raw.fingrid_readings (
                           dataset_id INTEGER, start_time TIMESTAMP, end_time TIMESTAMP,
                           value DOUBLE, loaded_at TIMESTAMP)""")
        # Idempotent: replace the period rather than adding to it
        con.execute("DELETE FROM raw.fingrid_readings WHERE start_time >= ? AND start_time < ?",
                    [period_start, period_end])
        con.register("new_rows", df)
        con.execute("""INSERT INTO raw.fingrid_readings
                       SELECT dataset_id, start_time, end_time, value, current_timestamp::TIMESTAMP
                       FROM new_rows""")
        loaded = con.execute("""SELECT COUNT(*) FROM raw.fingrid_readings
                                WHERE start_time >= ? AND start_time < ?""",
                             [period_start, period_end]).fetchone()[0]
        print(f"\nLoaded {loaded} rows into {DB_FILE} (fetched {len(df)}).")
        if loaded != len(df):
            raise RuntimeError("Row count in DuckDB doesn't match what was fetched.")
    finally:
        con.close()   # DuckDB allows one writer at a time, so close before running dbt


if __name__ == "__main__":
    main()
