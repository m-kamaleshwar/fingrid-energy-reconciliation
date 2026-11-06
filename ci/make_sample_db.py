"""Create a small synthetic fingrid.duckdb so CI can run dbt without the API.

The data is made up, but shaped like the real raw table: one day of 3-minute
readings for every dataset, with one deliberately missing production slot so
the models' handling of gaps is exercised. Production minus net exports equals
consumption, so the balance closes within tolerance.
"""
import duckdb
import pandas as pd

DB_FILE = "fingrid.duckdb"
START, END = "2026-10-06 00:00:00", "2026-10-07 00:00:00"

slots = pd.date_range(START, END, freq="3min", inclusive="left")
rows = []
for i, t in enumerate(slots):
    exports = {87: 300.0, 89: 200.0, 180: -150.0, 187: 50.0}   # net exports 400 MW
    production = 9000.0 + (i % 20) * 10
    values = {192: production, 193: production - sum(exports.values()), **exports}
    for dataset_id, value in values.items():
        if dataset_id == 192 and i == 100:
            continue  # one missing production reading
        rows.append((dataset_id, t, t + pd.Timedelta(minutes=3), value))

df = pd.DataFrame(rows, columns=["dataset_id", "start_time", "end_time", "value"])

con = duckdb.connect(DB_FILE)
con.execute("CREATE SCHEMA IF NOT EXISTS raw")
con.execute("DROP TABLE IF EXISTS raw.fingrid_readings")
con.register("sample", df)
con.execute("""CREATE TABLE raw.fingrid_readings AS
               SELECT dataset_id::INTEGER AS dataset_id, start_time, end_time,
                      value, current_timestamp::TIMESTAMP AS loaded_at
               FROM sample""")
print(f"Sample database created: {len(df)} rows in raw.fingrid_readings")
con.close()
