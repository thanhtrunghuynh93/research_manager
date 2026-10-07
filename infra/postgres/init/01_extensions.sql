-- Runs once on first cluster initialisation. Migration 0001 also creates it idempotently.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
