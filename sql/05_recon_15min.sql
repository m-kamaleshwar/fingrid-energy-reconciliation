-- =====================================================================
-- 05_recon_15min.sql
-- Reconciles the energy balance for every 15-minute block, using the
-- averaged real-time readings. Missing inputs give a NULL difference.
-- A window is complete only when all six real-time datasets have all 5
-- readings; otherwise the averages cover different moments.
-- Depends on: 03_core_aggregate_15min.sql
-- =====================================================================

CREATE TABLE IF NOT EXISTS stg_fin_grid.recon.FINGRID_15MIN_RECON (
    START_TIME          TIMESTAMP_TZ,
    END_TIME            TIMESTAMP_TZ,
    PRODUCTION          FLOAT,
    CONSUMPTION         FLOAT,
    NORTH_SWED          FLOAT,
    CENT_SWED           FLOAT,
    ESTONIA             FLOAT,
    NORWAY              FLOAT,
    NET_EXPORTS         FLOAT,
    RECONCILED          FLOAT,
    DIFFERENCE          FLOAT,
    DIFFERENCE_PERCENT  FLOAT,
    MIN_READINGS        NUMBER,     -- fewest readings behind any of the six averages
    WINDOW_COMPLETE     BOOLEAN,    -- TRUE when every dataset has all 5 readings
    LOADED_AT           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

-- Adds the columns to a table created before they existed
ALTER TABLE stg_fin_grid.recon.FINGRID_15MIN_RECON ADD COLUMN IF NOT EXISTS MIN_READINGS NUMBER;
ALTER TABLE stg_fin_grid.recon.FINGRID_15MIN_RECON ADD COLUMN IF NOT EXISTS WINDOW_COMPLETE BOOLEAN;


CREATE OR REPLACE PROCEDURE stg_fin_grid.recon.RECONCILE_FINGRID_15MIN(
    p_start_time TIMESTAMP_TZ,
    p_end_time   TIMESTAMP_TZ
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    DELETE FROM stg_fin_grid.recon.FINGRID_15MIN_RECON
    WHERE START_TIME >= :p_start_time
      AND START_TIME <  :p_end_time;

    INSERT INTO stg_fin_grid.recon.FINGRID_15MIN_RECON (
        START_TIME, END_TIME,
        PRODUCTION, CONSUMPTION,
        NORTH_SWED, CENT_SWED, ESTONIA, NORWAY,
        NET_EXPORTS, RECONCILED, DIFFERENCE, DIFFERENCE_PERCENT,
        MIN_READINGS, WINDOW_COMPLETE
    )
    WITH base AS (
        SELECT NAME, START_TIME, END_TIME, VALUE, READING_COUNT
        FROM stg_fin_grid.core.FINGRID_15MIN_AGG
        WHERE START_TIME >= :p_start_time
          AND END_TIME   <= :p_end_time
    ),
    pivoted AS (
        SELECT
            START_TIME,
            END_TIME,
            MAX(CASE WHEN NAME='production'  THEN VALUE END) AS PRODUCTION,
            MAX(CASE WHEN NAME='consumption' THEN VALUE END) AS CONSUMPTION,
            MAX(CASE WHEN NAME='north_swed'  THEN VALUE END) AS NORTH_SWED,
            MAX(CASE WHEN NAME='cent_swed'   THEN VALUE END) AS CENT_SWED,
            MAX(CASE WHEN NAME='estonia'     THEN VALUE END) AS ESTONIA,
            MAX(CASE WHEN NAME='norway'      THEN VALUE END) AS NORWAY,
            LEAST(
                COALESCE(MAX(CASE WHEN NAME='production'  THEN READING_COUNT END), 0),
                COALESCE(MAX(CASE WHEN NAME='consumption' THEN READING_COUNT END), 0),
                COALESCE(MAX(CASE WHEN NAME='north_swed'  THEN READING_COUNT END), 0),
                COALESCE(MAX(CASE WHEN NAME='cent_swed'   THEN READING_COUNT END), 0),
                COALESCE(MAX(CASE WHEN NAME='estonia'     THEN READING_COUNT END), 0),
                COALESCE(MAX(CASE WHEN NAME='norway'      THEN READING_COUNT END), 0)
            ) AS MIN_READINGS
        FROM base
        GROUP BY START_TIME, END_TIME
    )
    SELECT
        START_TIME,
        END_TIME,
        PRODUCTION,
        CONSUMPTION,
        NORTH_SWED,
        CENT_SWED,
        ESTONIA,
        NORWAY,
        (NORTH_SWED + CENT_SWED + ESTONIA + NORWAY)                   AS NET_EXPORTS,
        PRODUCTION - (NORTH_SWED + CENT_SWED + ESTONIA + NORWAY)      AS RECONCILED,
        (PRODUCTION - (NORTH_SWED + CENT_SWED + ESTONIA + NORWAY))
            - CONSUMPTION                                             AS DIFFERENCE,
        CASE WHEN PRODUCTION IS NULL OR PRODUCTION = 0 THEN NULL
             ELSE ABS((PRODUCTION - (NORTH_SWED + CENT_SWED + ESTONIA + NORWAY))
                      - CONSUMPTION) / PRODUCTION * 100
        END                                                           AS DIFFERENCE_PERCENT,
        MIN_READINGS,
        MIN_READINGS = 5                                              AS WINDOW_COMPLETE
    FROM pivoted;

    RETURN '15-min reconciliation completed';
END;
$$;
