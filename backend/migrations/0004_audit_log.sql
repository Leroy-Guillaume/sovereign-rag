-- Append-only audit trail of security-relevant actions (COMPLIANCE A.5.28,
-- LIPAD traceability). The application only ever INSERTs; the trigger makes
-- that a database guarantee rather than a convention.

CREATE TABLE audit_log (
    id          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor       text        NOT NULL,               -- user id from the API key
    action      text        NOT NULL,               -- e.g. 'document.upload'
    object_type text        NOT NULL,               -- 'document' | 'permission' | ...
    object_id   text        NOT NULL,
    detail      jsonb       NOT NULL DEFAULT '{}'
);

CREATE INDEX audit_log_at_idx ON audit_log (at DESC);

CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_rewrite
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
