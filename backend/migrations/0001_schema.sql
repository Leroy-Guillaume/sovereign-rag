CREATE EXTENSION IF NOT EXISTS vector;

-- Guard: the embedding model that built the index. Checked at boot; a mismatch
-- with the config refuses to start with an explicit message (switching embedding
-- models invalidates the whole index — same warning in the README).
CREATE TABLE embedding_config (
    singleton   boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    model       text    NOT NULL,
    dimensions  integer NOT NULL
);

CREATE TABLE documents (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        text        NOT NULL,
    content_type    text        NOT NULL CHECK (content_type IN ('pdf','docx','md','txt')),
    sha256          text        NOT NULL UNIQUE,          -- ingestion idempotency key
    size_bytes      bigint      NOT NULL,
    status          text        NOT NULL DEFAULT 'processing'
                                CHECK (status IN ('processing','ready','failed')),
    error           text,                                  -- message when status='failed'
    owner_id        text        NOT NULL,                  -- uploader user_id (from Phase 1 on)
    embedding_model text,                                  -- stamped at ingestion; belt-and-braces
    meta            jsonb       NOT NULL DEFAULT '{}',     -- title/author extracted from the file
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_owner_idx  ON documents (owner_id, created_at DESC);
CREATE INDEX documents_status_idx ON documents (status) WHERE status <> 'ready';

CREATE TABLE chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL,
    content      text NOT NULL,
    section      text,             -- heading path for md/docx ("Setup > Docker"), NULL otherwise
    page         integer,          -- PDF only
    embedding    vector(384) NOT NULL,   -- multilingual-e5-small; change = new migration + re-ingest
    tsv          tsvector GENERATED ALWAYS AS (
                     to_tsvector('french', content)
                  || to_tsvector('german', content)
                  || to_tsvector('english', content)
                 ) STORED,
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX chunks_embedding_idx ON chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX chunks_tsv_idx      ON chunks USING gin (tsv);
CREATE INDEX chunks_document_idx ON chunks (document_id);

CREATE TABLE conversations (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    text        NOT NULL,          -- no FK: users live in env config in Phase 1
    title      text        NOT NULL DEFAULT 'New conversation',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_user_idx ON conversations (user_id, created_at DESC);

CREATE TABLE messages (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id   uuid        NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    request_id        uuid        NOT NULL,   -- correlation id from middleware; audit join key (P2)
    role              text        NOT NULL CHECK (role IN ('user','assistant')),
    content           text        NOT NULL,
    sources           jsonb       NOT NULL DEFAULT '[]',
    -- audit snapshot, survives document deletion (LIPAD traceability):
    -- [{chunk_id, document_id, filename, section, page, excerpt, score, vec_rank, fts_rank}]
    model             text,                   -- assistant messages: "ollama/qwen3:4b"
    prompt_tokens     integer,
    completion_tokens integer,
    retrieval_ms      integer,                -- typed columns: P2 dashboard p50/p95 = trivial SQL
    generation_ms     integer,
    error_code        text,                   -- non-null on mid-stream failure or client disconnect
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at);
CREATE INDEX messages_created_idx     ON messages (created_at);      -- P2 dashboard aggregates
CREATE INDEX messages_request_idx     ON messages (request_id);
