-- =====================================================================
-- 01_setup_database.sql
-- Creates the database, schemas, raw table and dataset reference table.
-- Run once, before anything else. Safe to rerun.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS stg_fin_grid;
USE DATABASE stg_fin_grid;

CREATE SCHEMA IF NOT EXISTS stg_fin_grid.raw;    -- raw API data, loaded unchanged by Python
CREATE SCHEMA IF NOT EXISTS stg_fin_grid.ref;    -- reference data
CREATE SCHEMA IF NOT EXISTS stg_fin_grid.core;   -- normalised and aggregated readings
CREATE SCHEMA IF NOT EXISTS stg_fin_grid.recon;  -- reconciliation results
CREATE SCHEMA IF NOT EXISTS stg_fin_grid.ops;    -- orchestration

-- Raw readings, as loaded by load_to_snowflake.py
CREATE TABLE IF NOT EXISTS stg_fin_grid.raw.FINGRID_READINGS (
    DATASET_ID  INTEGER,
    START_TIME  TIMESTAMP_TZ,
    END_TIME    TIMESTAMP_TZ,
    VALUE       FLOAT,
    LOADED_AT   TIMESTAMP_TZ
);

-- The datasets used in the project
CREATE OR REPLACE TABLE stg_fin_grid.ref.FINGRID_DATASETS (
    NAME          VARCHAR,
    DATASET_ID    NUMBER,
    INTERVAL_MIN  NUMBER
);

INSERT INTO stg_fin_grid.ref.FINGRID_DATASETS (NAME, DATASET_ID, INTERVAL_MIN) VALUES
    ('production',       192, 3),
    ('consumption',      193, 3),
    ('north_swed',       87,  3),
    ('cent_swed',        89,  3),
    ('estonia',          180, 3),
    ('norway',           187, 3),
    ('prod_measurement', 74,  15),
    ('cons_measurement', 124, 15);
