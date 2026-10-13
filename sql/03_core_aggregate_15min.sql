-- =====================================================================
-- 03_core_aggregate_15min.sql
-- Averages normalised 3-minute readings into 15-minute blocks, counts how
-- many readings each average is based on (at most 5), and adds the native
-- 15-minute datasets (measured production and consumption).
-- Depends on: 02_core_normalize_3min.sql
-- =====================================================================

CREATE TABLE IF NOT EXISTS stg_fin_grid.core.FINGRID_15MIN_AGG (
    NAME        VARCHAR,
    START_TIME  TIMESTAMP_TZ,
    END_TIME    TIMESTAMP_TZ,
    VALUE          FLOAT,
    READING_COUNT  NUMBER,        -- 3-minute readings behind the average; NULL for native 15-minute data
    LOADED_AT      TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

-- Adds the column to a table created before READING_COUNT existed
ALTER TABLE stg_fin_grid.core.FINGRID_15MIN_AGG ADD COLUMN IF NOT EXISTS READING_COUNT NUMBER;


CREATE OR REPLACE PROCEDURE stg_fin_grid.core.AGGREGATE_FINGRID_15MIN(
    p_start_time TIMESTAMP_TZ,
    p_end_time   TIMESTAMP_TZ
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    -- Clear existing rows for this window (idempotent by period)
    DELETE FROM stg_fin_grid.core.FINGRID_15MIN_AGG
    WHERE START_TIME >= :p_start_time
      AND START_TIME <  :p_end_time;

    ----------------------------------------------------------------------
    -- 1. Aggregate normalised 3-minute data into 15-minute blocks.
    --    DATEADD is used because TIME_SLICE doesn't accept TIMESTAMP_TZ.
    --    Aliases START_15 and END_15 must not clash with the column
    --    START_TIME, or GROUP BY would use the raw 3-minute timestamps.
    ----------------------------------------------------------------------
    INSERT INTO stg_fin_grid.core.FINGRID_15MIN_AGG (NAME, START_TIME, END_TIME, VALUE, READING_COUNT)
    SELECT
        NAME,
        DATEADD('minute', -MOD(DATE_PART('minute', START_TIME), 15),
                DATE_TRUNC('minute', START_TIME))                          AS START_15,
        DATEADD('minute', 15,
                DATEADD('minute', -MOD(DATE_PART('minute', START_TIME), 15),
                        DATE_TRUNC('minute', START_TIME)))                 AS END_15,
        AVG(VALUE)                                                         AS VALUE,
        COUNT(*)                                                           AS READING_COUNT
    FROM stg_fin_grid.core.FINGRID_3MIN_NORMALIZED
    WHERE START_TIME >= :p_start_time
      AND START_TIME <  :p_end_time
    GROUP BY NAME, START_15, END_15;

    ----------------------------------------------------------------------
    -- 2. Load native 15-minute datasets (prod_measurement, cons_measurement)
    ----------------------------------------------------------------------
    INSERT INTO stg_fin_grid.core.FINGRID_15MIN_AGG (NAME, START_TIME, END_TIME, VALUE)
    SELECT
        d.NAME,
        r.START_TIME,
        r.END_TIME,
        r.VALUE
    FROM stg_fin_grid.raw.FINGRID_READINGS r
    JOIN stg_fin_grid.ref.FINGRID_DATASETS d
        ON r.DATASET_ID = d.DATASET_ID
    WHERE d.INTERVAL_MIN = 15
      AND r.START_TIME >= :p_start_time
      AND r.END_TIME   <= :p_end_time;

    RETURN '15-min aggregation completed';
END;
$$;
