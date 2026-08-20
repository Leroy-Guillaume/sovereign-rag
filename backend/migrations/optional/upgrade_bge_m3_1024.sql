-- OPTIONAL operator-applied upgrade: switch the embedding space to 1024
-- dimensions (BAAI/bge-m3). The migration runner only picks up
-- backend/migrations/*.sql; nothing under optional/ ever runs on its own.
--
-- Embeddings from different models are not comparable, so this upgrade is
-- destructive by necessity: the corpus must be re-ingested. Full walkthrough
-- (env vars, image rebuild with the matching baked weights, re-upload) in the
-- README's "Embedding model" section. Apply with:
--
--   psql "$DATABASE_URL" -f backend/migrations/optional/upgrade_bge_m3_1024.sql
--
-- then restart the API: the boot guard re-registers the model from the
-- environment, and the demo seed re-ingests data/demo automatically.
BEGIN;

-- every vector and every chunk derived from the old space goes
TRUNCATE documents CASCADE;

-- the config row is deleted, not updated: the boot guard re-inserts it from
-- EMBEDDING_MODEL / EMBEDDING_DIMENSIONS, so this file never contradicts the
-- environment the operator actually configured
DELETE FROM embedding_config;

DROP INDEX chunks_embedding_idx;
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024);
CREATE INDEX chunks_embedding_idx ON chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

COMMIT;

-- outside the transaction: matview refresh keeps the term statistics aligned
-- with the now-empty corpus (the boot refresh would do it too; this keeps the
-- database consistent even if the API does not restart immediately)
REFRESH MATERIALIZED VIEW lexeme_df;
