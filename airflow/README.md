# Airflow orchestration

Daily orchestration of the Fingrid -> Snowflake reconciliation: load one UTC day
of Fingrid open data into `RAW.FINGRID_READINGS`, then run the Snowflake
pipeline (CORE normalise, 15-minute aggregate, 3-minute and 15-minute RECON)
for the same window.

Airflow 3.4, CeleryExecutor, Docker Compose.

## The DAG

`dags/fingrid_snowflake_daily.py` - two tasks:

| Task | What it does |
|---|---|
| `load_raw_to_snowflake` | Runs `load_to_snowflake.py` for the run's data interval. Fetches the 8 Fingrid datasets and replaces that window's rows. |
| `run_fingrid_pipeline`  | Calls `stg_fin_grid.ops.RUN_FINGRID_PIPELINE(start, end)` for the same window. |

One DAG run covers one UTC day: the run for day D has data interval
`[D 00:00, D+1 00:00)` and fires at 00:00 UTC on D+1.

### Why these two settings matter

**`CronDataIntervalTimetable`, not a bare cron string.** In Airflow 3 a plain
cron expression selects `CronTriggerTimetable`, which has no data interval -
`data_interval_start` and `data_interval_end` are both the trigger time. The
window passed to the scripts would collapse to zero length.

**`autocommit=True` on the Snowflake task.** The default (`False`) makes the
hook open an explicit transaction before `CALL`. The procedures invoked inside
manage their own transaction scope, and Snowflake fails with
*"Scoped transaction started in stored procedure is incomplete and it was
rolled back"*.

### Re-runs and backfills

The loader deletes the window before writing, and the stored procedure
recomputes it, so re-running a day is safe. That is what makes retries and
backfills free.

## Setup

1. `cp .env.example .env` and set `FERNET_KEY`.
2. Point the repo mount in `docker-compose.yaml` at your clone of
   [fingrid-energy-reconciliation](https://github.com/m-kamaleshwar/fingrid-energy-reconciliation).
3. `docker compose build && docker compose up -d`
4. Create the Airflow **Connection** `snowflake_fingrid` (type Snowflake; login,
   password, and `{"account": "..."}` in Extra) and the **Variable**
   `fingrid_api_key`.
5. Verify, then unpause:

```bash
docker compose exec airflow-scheduler ls /opt/airflow/fingrid-repo
docker compose exec airflow-scheduler airflow dags list-import-errors
docker compose exec airflow-scheduler airflow connections test snowflake_fingrid
docker compose exec airflow-scheduler airflow dags test fingrid_snowflake_daily 2026-10-07
```

Note: `airflow dags test <date>` runs the interval **ending** at that date, so
pass the day after the one you want.

## Not included

Credentials. The Snowflake connection and the Fingrid API key live in Airflow's
own connection and variable store, not in this repo.
