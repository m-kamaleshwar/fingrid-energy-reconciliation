"""
Daily Fingrid -> Snowflake reconciliation.

One DAG run == one UTC day. The run for day D executes at 00:00 UTC on D+1,
passing --start D T00:00:00Z --end (D+1) T00:00:00Z, which matches the
exclusive-end convention the repo scripts already use.

Re-running a day is safe: load_to_snowflake.py DELETEs the window before
write_pandas, and RUN_FINGRID_PIPELINE recomputes CORE/RECON for the window.
That is what makes retries and backfills free.

Airflow 3.x. On 2.x, change the imports as noted below.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pendulum

# Airflow 3.x import paths. On Airflow 2.x use:
#   from airflow import DAG
#   from airflow.operators.bash import BashOperator
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.timetables.interval import CronDataIntervalTimetable

# Where the repo is checked out on the Airflow worker.
REPO_DIR = os.environ.get("FINGRID_REPO_DIR", "/opt/airflow/fingrid-energy-reconciliation")

# Airflow Connection holding the Snowflake creds, and Variable holding the API key.
SNOWFLAKE_CONN_ID = "snowflake_fingrid"
API_KEY_VAR = "fingrid_api_key"

# Secrets reach the script as env vars, resolved at render time from the
# Connection/Variable store. Nothing lands in git, and Airflow's secrets
# masker redacts the password in logs and the rendered-template view.
SCRIPT_ENV = {
    "SNOWFLAKE_USER": f"{{{{ conn.{SNOWFLAKE_CONN_ID}.login }}}}",
    "SNOWFLAKE_PASSWORD": f"{{{{ conn.{SNOWFLAKE_CONN_ID}.password }}}}",
    "SNOWFLAKE_ACCOUNT": f"{{{{ conn.{SNOWFLAKE_CONN_ID}.extra_dejson.account }}}}",
    "FINGRID_API_KEY": f"{{{{ var.value.{API_KEY_VAR} }}}}",
}

default_args = {
    "owner": "kamal",
    # The API is flaky and paged; the load is idempotent, so retry freely.
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
}

with DAG(
    dag_id="fingrid_snowflake_daily",
    description="Daily Fingrid open-data load and balance reconciliation in Snowflake",
    # NOT a bare cron string: in Airflow 3 that selects CronTriggerTimetable,
    # which has NO data interval (data_interval_start == data_interval_end), so
    # the window passed to the scripts collapses to zero length. This timetable
    # gives the Airflow 2 behaviour the window mapping depends on: run for day D
    # has data_interval [D 00:00, D+1 00:00) and fires at 00:00 on D+1 UTC.
    schedule=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"),
    start_date=pendulum.datetime(2026, 10, 6, tz="UTC"),
    # Turn this on only when you actually want history; see the backfill note.
    catchup=False,
    # Serialises backfills -> protects the Fingrid API and avoids two runs
    # writing the same RAW window. Do not raise this.
    max_active_runs=1,
    default_args=default_args,
    tags=["fingrid", "snowflake", "reconciliation"],
    doc_md=__doc__,
) as dag:

    # 1. Extract from the Fingrid API and replace the day's rows in RAW.FINGRID_READINGS.
    #    Raises RuntimeError on a per-dataset row-count mismatch -> a real failure.
    load_raw = BashOperator(
        task_id="load_raw_to_snowflake",
        bash_command=(
            "cd {{ params.repo_dir }} && "
            "python load_to_snowflake.py "
            "--start {{ data_interval_start.format('YYYY-MM-DDTHH:mm:ss') }}Z "
            "--end {{ data_interval_end.format('YYYY-MM-DDTHH:mm:ss') }}Z"
        ),
        params={"repo_dir": REPO_DIR},
        env=SCRIPT_ENV,
        append_env=True,
        # API paging over 8 datasets; generous but bounded.
        execution_timeout=timedelta(minutes=45),
    )

    # 2. CORE normalise -> 15min aggregate -> RECON 3min + 15min, in one call.
    run_pipeline = SQLExecuteQueryOperator(
        task_id="run_fingrid_pipeline",
        conn_id=SNOWFLAKE_CONN_ID,
        sql="""
            CALL stg_fin_grid.ops.RUN_FINGRID_PIPELINE(
                '{{ data_interval_start.format('YYYY-MM-DD HH:mm:ss') }}+00:00'::TIMESTAMP_TZ,
                '{{ data_interval_end.format('YYYY-MM-DD HH:mm:ss') }}+00:00'::TIMESTAMP_TZ
            )
        """,
        # REQUIRED. Default is False, which makes the hook open an explicit
        # transaction before CALL. The procedures invoked inside manage their
        # own transaction scope, and Snowflake then fails the call with
        # "Scoped transaction started in stored procedure is incomplete and it
        # was rolled back". Snowsight has autocommit on, which is why the same
        # CALL works by hand.
        autocommit=True,
        show_return_value_in_logs=True,
        execution_timeout=timedelta(minutes=30),
    )

    load_raw >> run_pipeline
