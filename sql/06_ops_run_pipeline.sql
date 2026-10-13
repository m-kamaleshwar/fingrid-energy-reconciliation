-- =====================================================================
-- 06_ops_run_pipeline.sql
-- Runs the whole Snowflake pipeline for a period, in the right order.
-- Depends on: files 01 to 05
-- =====================================================================

CREATE OR REPLACE PROCEDURE stg_fin_grid.ops.RUN_FINGRID_PIPELINE(
    p_start_time TIMESTAMP_TZ,
    p_end_time   TIMESTAMP_TZ
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    -- Step 1: Normalise 3-minute readings
    CALL stg_fin_grid.core.NORMALIZE_FINGRID_3MIN(:p_start_time, :p_end_time);

    -- Step 2: Fill empty slots after corrected records. SWITCHED OFF:
    -- filled values breached tolerance in 4 of 9 reconcilable cases,
    -- against about 1% for original readings (1 to 10 Oct 2026).
    -- CALL stg_fin_grid.core.FILL_MISSING_3MIN_SLOTS(:p_start_time, :p_end_time);

    -- Step 3: Aggregate into 15-minute blocks
    CALL stg_fin_grid.core.AGGREGATE_FINGRID_15MIN(:p_start_time, :p_end_time);

    -- Step 4: Reconcile 3-minute slots
    CALL stg_fin_grid.recon.RECONCILE_FINGRID_3MIN(:p_start_time, :p_end_time);

    -- Step 5: Reconcile 15-minute blocks
    CALL stg_fin_grid.recon.RECONCILE_FINGRID_15MIN(:p_start_time, :p_end_time);

    RETURN 'Fingrid pipeline completed for window: ' || :p_start_time || ' to ' || :p_end_time;
END;
$$;

-- Example run (dates in UTC, end date exclusive):
-- CALL stg_fin_grid.ops.RUN_FINGRID_PIPELINE(
--     '2026-10-06T00:00:00Z'::TIMESTAMP_TZ,
--     '2026-10-10T00:00:00Z'::TIMESTAMP_TZ
-- );
