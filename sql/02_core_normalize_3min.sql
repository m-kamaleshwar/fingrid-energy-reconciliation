-- =====================================================================
-- 02_core_normalize_3min.sql
-- Gives every 3-minute reading its own slot.
-- Some real-time records claim to last 6 minutes; their end time is wrong,
-- so each record keeps only its first slot and is labelled 'endtime_fixed'.
-- Depends on: 01_setup_database.sql
-- =====================================================================

CREATE TABLE IF NOT EXISTS stg_fin_grid.core.FINGRID_3MIN_NORMALIZED (
    NAME        VARCHAR,
    START_TIME  TIMESTAMP_TZ,
    END_TIME    TIMESTAMP_TZ,
    VALUE       FLOAT,
    STATUS      VARCHAR,
    LOADED_AT   TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);


CREATE OR REPLACE PROCEDURE stg_fin_grid.core.NORMALIZE_FINGRID_3MIN(
    p_start_time TIMESTAMP_TZ,
    p_end_time   TIMESTAMP_TZ
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    -- Clear existing rows for this window (idempotent by period)
    DELETE FROM stg_fin_grid.core.FINGRID_3MIN_NORMALIZED
    WHERE START_TIME >= :p_start_time
      AND START_TIME <  :p_end_time;

    INSERT INTO stg_fin_grid.core.FINGRID_3MIN_NORMALIZED (NAME, START_TIME, END_TIME, VALUE, STATUS)
    SELECT
        d.NAME,
        r.START_TIME,
        r.START_TIME + INTERVAL '3' MINUTE AS END_TIME,
        r.VALUE,
        CASE
            WHEN DATEDIFF('minute', r.START_TIME, r.END_TIME) > 3
                THEN 'endtime_fixed'
            ELSE 'original'
        END AS STATUS
    FROM stg_fin_grid.raw.FINGRID_READINGS r
    JOIN stg_fin_grid.ref.FINGRID_DATASETS d
        ON r.DATASET_ID = d.DATASET_ID
    WHERE d.INTERVAL_MIN = 3
      AND r.START_TIME >= :p_start_time
      AND r.START_TIME <  :p_end_time;

    RETURN '3-min normalization completed';
END;
$$;


-- If a corrected record's next slot has no reading of its own, carry the
-- value into it ('filled_from_previous').
-- NOT USED BY THE PIPELINE: tested on 1 to 10 Oct 2026, filled values breached
-- tolerance in 4 of 9 reconcilable cases, against about 1% for original
-- readings. Kept for reference and further testing.
-- Runs after NORMALIZE_FINGRID_3MIN, which clears the window first.
CREATE OR REPLACE PROCEDURE stg_fin_grid.core.FILL_MISSING_3MIN_SLOTS(
    p_start_time TIMESTAMP_TZ,
    p_end_time   TIMESTAMP_TZ
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    INSERT INTO stg_fin_grid.core.FINGRID_3MIN_NORMALIZED (
        NAME, START_TIME, END_TIME, VALUE, STATUS
    )
    SELECT
        n.NAME,
        n.START_TIME + INTERVAL '3' MINUTE AS START_TIME,
        n.START_TIME + INTERVAL '6' MINUTE AS END_TIME,
        n.VALUE,
        'filled_from_previous'
    FROM stg_fin_grid.core.FINGRID_3MIN_NORMALIZED n
    WHERE n.START_TIME >= :p_start_time
      AND n.END_TIME   <  :p_end_time
      AND n.STATUS = 'endtime_fixed'
      AND NOT EXISTS (
            SELECT 1
            FROM stg_fin_grid.core.FINGRID_3MIN_NORMALIZED x
            WHERE x.NAME = n.NAME
              AND x.START_TIME = n.START_TIME + INTERVAL '3' MINUTE
      );

    RETURN 'Missing 3-min slots filled';
END;
$$;
