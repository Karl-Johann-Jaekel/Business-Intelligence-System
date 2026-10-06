-- Runs once on first container start.
-- warehouse: raw/staging/intermediate/marts/ops (created by POSTGRES_DB)
-- erp:       simulated source system ("ERP") holding Olist transactional data
-- dagster:   Dagster run/event storage
CREATE DATABASE erp;
CREATE DATABASE dagster;
