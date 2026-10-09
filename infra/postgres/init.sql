-- Runs once on first container start.
-- warehouse: raw/staging/intermediate/marts/ops/knowledge (created by POSTGRES_DB)
-- erp:       simulated source system ("ERP") holding Olist transactional data
-- dagster:   Dagster run/event storage
-- keycloak:  Keycloak (VPS; locally Keycloak runs with file storage)
CREATE DATABASE erp;
CREATE DATABASE dagster;
CREATE DATABASE keycloak;
