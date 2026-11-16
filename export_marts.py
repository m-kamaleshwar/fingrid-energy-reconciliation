"""Export the dbt output tables from fingrid.duckdb to CSV for Power BI.

Run from the repo root, after `dbt build`:

    python export_marts.py              # overwrite the CSVs with the current tables
    python export_marts.py --merge      # keep older history already in the CSVs

dbt-duckdb builds every model in the `main` schema (raw data stays in `raw`),
so the tables are exported by name:

    main.recon_3min          one row per 3-minute slot, the balance check
    main.int_readings_3min   one row per reading, with the end-time status
    main.fingrid_datasets    the dataset reference seed

--merge is for daily runs where dbt only rebuilds a recent window. Rows in an
existing CSV that fall outside the newly built time range are kept, and rows
inside it are replaced, so reruns never duplicate a slot.
"""

import argparse
import os
import sys
from pathlib import Path

import duckdb

DB_FILE = "fingrid.duckdb"
SCHEMA = "main"
# table name -> time column used by --merge (None = always overwrite)
TABLES = {
    "recon_3min": "start_time",
    "int_readings_3min": "start_time",
    "fingrid_datasets": None,
}


def export_table(con, table, time_col, out_dir, merge):
    source = f'"{SCHEMA}"."{table}"'
    target = out_dir / f"{table}.csv"
    order_by = f'order by "{time_col}"' if time_col else ""
    query = f"select * from {source}"

    if merge and time_col and target.exists():
        lo, hi = con.execute(
            f'select min("{time_col}"), max("{time_col}") from {source}'
        ).fetchone()
        if lo is not None:
            # Read the old CSV as text and cast to the table's own types, so an
            # all-empty column in the old file cannot change a column's type.
            columns = con.execute(f"describe select * from {source}").fetchall()
            casts = ", ".join(f'cast("{c[0]}" as {c[1]}) as "{c[0]}"' for c in columns)
            old_rows = (
                f"select {casts} from read_csv('{target.as_posix()}', "
                f"header = true, all_varchar = true) "
                f"where cast(\"{time_col}\" as timestamp) < timestamp '{lo}' "
                f"or cast(\"{time_col}\" as timestamp) > timestamp '{hi}'"
            )
            query = f"{old_rows} union all select * from {source}"

    # Write to a temporary file first, so a failed run never leaves a half file
    temp = target.with_suffix(".csv.tmp")
    con.execute(
        f"copy (select * from ({query}) {order_by}) "
        f"to '{temp.as_posix()}' (header, delimiter ',')"
    )
    os.replace(temp, target)
    rows = con.execute(
        f"select count(*) from read_csv('{target.as_posix()}', header = true, all_varchar = true)"
    ).fetchone()[0]
    print(f"{SCHEMA}.{table}: {rows} rows in {target.as_posix()}")


def main():
    parser = argparse.ArgumentParser(description="Export dbt tables from DuckDB to CSV.")
    parser.add_argument("--db", default=DB_FILE, help="DuckDB file (default: fingrid.duckdb)")
    parser.add_argument("--out", default="exports", help="output folder (default: exports)")
    parser.add_argument("--merge", action="store_true",
                        help="keep rows already in the CSVs that are outside the rebuilt period")
    args = parser.parse_args()

    if not Path(args.db).exists():
        sys.exit(f"DuckDB file not found: {args.db} (run load_to_duckdb.py and dbt build first)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(args.db, read_only=True)
    try:
        existing = {row[0] for row in con.execute(
            "select table_name from information_schema.tables where table_schema = ?",
            [SCHEMA]).fetchall()}
        missing = [t for t in TABLES if t not in existing]
        if missing:
            sys.exit(f"Not found in schema '{SCHEMA}': {', '.join(missing)} (run dbt build first)")
        for table, time_col in TABLES.items():
            export_table(con, table, time_col, out_dir, args.merge)
    finally:
        con.close()


if __name__ == "__main__":
    main()
