-- Per-document access control (Phase 2).
--
-- A user can retrieve, list and read a document when they own it or when a
-- permission row grants it to their user_id, or to '*' (every authenticated
-- user). The predicate is applied inside EACH retrieval leg, before fusion
-- (see ARCHITECTURE 3.9): filtering after fusion would waste candidates and
-- leak rank information.
CREATE TABLE document_permissions (
    document_id uuid        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    principal   text        NOT NULL,  -- a user_id, or '*' for every authenticated user
    granted_by  text        NOT NULL,
    granted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, principal)
);

CREATE INDEX document_permissions_principal_idx ON document_permissions (principal);

-- Phase 1 visibility was "every authenticated user sees everything"; the
-- corpora ingested under that rule keep it. New uploads start private.
INSERT INTO document_permissions (document_id, principal, granted_by)
SELECT id, '*', 'migration:phase1-visibility' FROM documents;
