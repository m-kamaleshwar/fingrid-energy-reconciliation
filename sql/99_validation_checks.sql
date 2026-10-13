-- =====================================================================
-- 99_validation_checks.sql
-- Checks to run after loading and after RUN_FINGRID_PIPELINE.
-- Set the period once here; every query below uses it.
-- =====================================================================

SET start_time = '2026-10-06T00:00:00Z'::TIMESTAMP_TZ;
SET end_time   = '2026-10-10T00:00:00Z'::TIMESTAMP_TZ;


-- 1. RAW: rows and time range per dataset.
--    Counts should match "Records fetched" in the Python output.
SELECT DATASET_ID, COUNT(*) AS ROW_COUNT,
       MIN(START_TIME) AS FIRST_READING, MAX(START_TIME) AS LAST_READING
FROM stg_fin_grid.raw.FINGRID_READINGS
WHERE START_TIME >= $start_time AND START_TIME < $end_time
GROUP BY DATASET_ID
ORDER BY DATASET_ID;


-- 2. RAW: no duplicate readings. Expected: no rows.
SELECT DATASET_ID, START_TIME, END_TIME, COUNT(*) AS COPIES
FROM stg_fin_grid.raw.FINGRID_READINGS
WHERE START_TIME >= $start_time AND START_TIME < $end_time
GROUP BY DATASET_ID, START_TIME, END_TIME
HAVING COUNT(*) > 1;


-- 3. CORE: 15-minute blocks start only at :00, :15, :30 or :45.
SELECT DISTINCT DATE_PART('minute', START_TIME) AS MINUTE_
FROM stg_fin_grid.core.FINGRID_15MIN_AGG
WHERE START_TIME >= $start_time AND START_TIME < $end_time
ORDER BY 1;


-- 4. CORE: no duplicate 15-minute blocks per dataset. Expected: no rows.
SELECT NAME, START_TIME, COUNT(*) AS COPIES
FROM stg_fin_grid.core.FINGRID_15MIN_AGG
WHERE START_TIME >= $start_time AND START_TIME < $end_time
GROUP BY NAME, START_TIME
HAVING COUNT(*) > 1;


-- 5. RECON: summary. Compare with the Python summary in output.txt.
--    With gap filling off:
--    1 to 6 Oct 2026:  2,400 slots, 530 and 485 missing, 13 breaches, 72.35 MW
--    6 to 10 Oct 2026: 1,920 slots, 394 and 344 missing, 21 breaches, 110.57 MW
SELECT
    COUNT(*)                                    AS TOTAL_SLOTS,
    SUM(IFF(PRODUCTION IS NULL, 1, 0))          AS PRODUCTION_MISSING,
    SUM(IFF(CONSUMPTION IS NULL, 1, 0))         AS CONSUMPTION_MISSING,
    SUM(IFF(DIFFERENCE_PERCENT > 0.5, 1, 0))    AS BREACHES,
    ROUND(MAX(ABS(DIFFERENCE)), 2)              AS MAX_ABS_DIFFERENCE
FROM stg_fin_grid.recon.FINGRID_3MIN_RECON
WHERE START_TIME >= $start_time AND START_TIME < $end_time;


-- 6. RECON: slots with no reading in any dataset (system-wide gaps).
SELECT COUNT(*) AS EMPTY_SLOTS
FROM stg_fin_grid.recon.FINGRID_3MIN_RECON
WHERE START_TIME >= $start_time AND START_TIME < $end_time
  AND PRODUCTION IS NULL AND CONSUMPTION IS NULL
  AND NORTH_SWED IS NULL AND CENT_SWED IS NULL
  AND ESTONIA IS NULL AND NORWAY IS NULL;


-- 7. RECON: breaches by production status.
--    The evidence that corrected end times reconcile like original readings.
SELECT
    PRODUCTION_STATUS,
    COUNT(*)                                    AS SLOTS,
    COUNT(DIFFERENCE)                           AS COMPLETE,
    SUM(IFF(DIFFERENCE_PERCENT > 0.5, 1, 0))    AS BREACHES
FROM stg_fin_grid.recon.FINGRID_3MIN_RECON
WHERE START_TIME >= $start_time AND START_TIME < $end_time
GROUP BY PRODUCTION_STATUS
ORDER BY PRODUCTION_STATUS;


-- 8. RECON 15-min: breaches by window completeness.
--    Compare with "Breaches by window completeness" in the Python output.
--    Large differences in incomplete windows point to averages that
--    cover different moments, not to a real imbalance.
SELECT
    WINDOW_COMPLETE,
    COUNT(*)                                    AS WINDOWS,
    SUM(IFF(DIFFERENCE_PERCENT > 0.5, 1, 0))    AS BREACHES,
    ROUND(MAX(ABS(DIFFERENCE)), 2)              AS MAX_ABS_DIFFERENCE
FROM stg_fin_grid.recon.FINGRID_15MIN_RECON
WHERE START_TIME >= $start_time AND START_TIME < $end_time
GROUP BY WINDOW_COMPLETE
ORDER BY WINDOW_COMPLETE;
