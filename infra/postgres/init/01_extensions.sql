-- Runs once on first cluster initialisation. Migrations also create these idempotently.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
