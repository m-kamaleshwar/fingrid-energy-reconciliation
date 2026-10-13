-- =====================================================================
-- 04_recon_3min.sql
-- Reconciles the energy balance for every 3-minute slot:
--     difference = (production - net exports) - consumption
-- Built on the expected grid of slots, so slots with no data stay visible.
-- Missing inputs give a NULL difference, never a false one.
-- Depends on: 02_core_normalize_3min.sql
-- =====================================================================

CREATE TABLE IF NOT EXISTS stg_fin_grid.recon.FINGRID_3MIN_RECON (
    START_TIME          TIMESTAMP_TZ,
    END_TIME            TIMESTAMP_TZ,
    PRODUCTION          FLOAT,  PRODUCTION_STATUS   VARCHAR,
    CONSUMPTION         FLOAT,  CONSUMPTION_STATUS  VARCHAR,
    NORTH_SWED          FLOAT,  NORTH_SWED_STATUS   VARCHAR,
    CENT_SWED           FLOAT,  CENT_SWED_STATUS    VARCHAR,
    ESTONIA             FLOAT,  ESTONIA_STATUS      VARCHAR,
    NORWAY              FLOAT,  NORWAY_STATUS       VARCHAR,
    NET_EXPORTS         FLOAT,
    RECONCILED          FLOAT,
    DIFFERENCE          FLOAT,
    DIFFERENCE_PERCENT  FLOAT,
    LOADED_AT           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);


CREATE OR REPLACE PROCEDURE stg_fin_grid.recon.RECONCILE_FINGRID_3MIN(
    p_start_time TIMESTAMP_TZ,
    p_end_time   TIMESTAMP_TZ
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    DELETE FROM stg_fin_grid.recon.FINGRID_3MIN_RECON
    WHERE START_TIME >= :p_start_time
      AND START_TIME <  :p_end_time;

    INSERT INTO stg_fin_grid.recon.FINGRID_3MIN_RECON (
        START_TIME, END_TIME,
        PRODUCTION, CONSUMPTION,
        NORTH_SWED, CENT_SWED, ESTONIA, NORWAY,
        PRODUCTION_STATUS, CONSUMPTION_STATUS,
        NORTH_SWED_STATUS, CENT_SWED_STATUS, ESTONIA_STATUS, NORWAY_STATUS,
        NET_EXPORTS, RECONCILED, DIFFERENCE, DIFFERENCE_PERCENT
    )
    WITH grid AS (
        -- Every 3-minute slot from the start time (covers about 5.7 years)
        SELECT DATEADD('minute', 3 * (ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1),
                       :p_start_time) AS START_TIME
        FROM TABLE(GENERATOR(ROWCOUNT => 1000000))
    ),
    grid_window AS (
        SELECT START_TIME, DATEADD('minute', 3, START_TIME) AS END_TIME
        FROM grid
        WHERE START_TIME < :p_end_time
    ),
    pivoted AS (
        SELECT
            START_TIME,
            MAX(CASE WHEN NAME='production'  THEN VALUE END)  AS PRODUCTION,
            MAX(CASE WHEN NAME='consumption' THEN VALUE END)  AS CONSUMPTION,
            MAX(CASE WHEN NAME='north_swed'  THEN VALUE END)  AS NORTH_SWED,
            MAX(CASE WHEN NAME='cent_swed'   THEN VALUE END)  AS CENT_SWED,
            MAX(CASE WHEN NAME='estonia'     THEN VALUE END)  AS ESTONIA,
            MAX(CASE WHEN NAME='norway'      THEN VALUE END)  AS NORWAY,
            MAX(CASE WHEN NAME='production'  THEN STATUS END) AS PRODUCTION_STATUS,
            MAX(CASE WHEN NAME='consumption' THEN STATUS END) AS CONSUMPTION_STATUS,
            MAX(CASE WHEN NAME='north_swed'  THEN STATUS END) AS NORTH_SWED_STATUS,
            MAX(CASE WHEN NAME='cent_swed'   THEN STATUS END) AS CENT_SWED_STATUS,
            MAX(CASE WHEN NAME='estonia'     THEN STATUS END) AS ESTONIA_STATUS,
            MAX(CASE WHEN NAME='norway'      THEN STATUS END) AS NORWAY_STATUS
        FROM stg_fin_grid.core.FINGRID_3MIN_NORMALIZED
        WHERE START_TIME >= :p_start_time
          AND START_TIME <  :p_end_time
        GROUP BY START_TIME
    )
    SELECT
        g.START_TIME,
        g.END_TIME,
        p.PRODUCTION, p.CONSUMPTION,
        p.NORTH_SWED, p.CENT_SWED, p.ESTONIA, p.NORWAY,
        p.PRODUCTION_STATUS, p.CONSUMPTION_STATUS,
        p.NORTH_SWED_STATUS, p.CENT_SWED_STATUS, p.ESTONIA_STATUS, p.NORWAY_STATUS,
        (p.NORTH_SWED + p.CENT_SWED + p.ESTONIA + p.NORWAY)                  AS NET_EXPORTS,
        p.PRODUCTION - (p.NORTH_SWED + p.CENT_SWED + p.ESTONIA + p.NORWAY)   AS RECONCILED,
        (p.PRODUCTION - (p.NORTH_SWED + p.CENT_SWED + p.ESTONIA + p.NORWAY))
            - p.CONSUMPTION                                                  AS DIFFERENCE,
        CASE WHEN p.PRODUCTION IS NULL OR p.PRODUCTION = 0 THEN NULL
             ELSE ABS((p.PRODUCTION - (p.NORTH_SWED + p.CENT_SWED + p.ESTONIA + p.NORWAY))
                      - p.CONSUMPTION) / p.PRODUCTION * 100
        END                                                                  AS DIFFERENCE_PERCENT
    FROM grid_window g
    LEFT JOIN pivoted p
        ON p.START_TIME = g.START_TIME;

    RETURN '3-min reconciliation completed';
END;
$$;
