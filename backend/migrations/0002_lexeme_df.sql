-- Document frequency per lexeme over the tri-config tsvector column.
--
-- Hybrid search uses this to keep only informative query terms: a term whose
-- every lexeme is either absent from the corpus or present in a large share
-- of it cannot discriminate, and inside an AND conjunction it only destroys
-- recall. The view is intentionally a snapshot: the ingestion service
-- refreshes it after each successful ingestion and at boot (REFRESH
-- MATERIALIZED VIEW CONCURRENTLY, ~1 s on a 10k-chunk corpus). Between
-- refreshes the frequencies are slightly stale, which is harmless for a
-- band filter, and the filter is exclusion-only: a term absent from the
-- snapshot always passes, so degraded statistics can weaken the filter but
-- never silence the lexical leg.
-- `total` carries the snapshot's own corpus size: the band ceiling derived
-- from it stays consistent with ndoc even when the snapshot is stale, which
-- a ceiling computed from the live chunks table would not be.
CREATE MATERIALIZED VIEW lexeme_df AS
SELECT s.word, s.ndoc, t.total
FROM ts_stat('SELECT tsv FROM chunks') AS s
CROSS JOIN (SELECT count(*) AS total FROM chunks) AS t;

-- Required by REFRESH MATERIALIZED VIEW CONCURRENTLY, and the lookup path
-- for the band filter's word probes.
CREATE UNIQUE INDEX lexeme_df_word_idx ON lexeme_df (word);
