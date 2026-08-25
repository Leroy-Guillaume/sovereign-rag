-- Compliance audits: long-running agent jobs with per-requirement
-- checkpointing. The row IS the checkpoint: findings append as each
-- requirement is evaluated, so a restart resumes exactly where the job
-- stopped instead of re-paying the whole run.

CREATE TABLE audits (
    id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id             text        NOT NULL,
    regulation_id        uuid,                     -- source document, no FK: the
    regulation_filename  text        NOT NULL,     -- audit outlives deletion
    status               text        NOT NULL DEFAULT 'queued'
                                     CHECK (status IN ('queued','running','completed','failed')),
    error                text,
    -- Cartographer output: [{"ref": "art. 8", "text": "..."}]
    requirements         jsonb       NOT NULL DEFAULT '[]',
    -- One entry per evaluated requirement, appended as the job progresses:
    -- [{"ref", "verdict": "compliant"|"gap"|"indeterminate", "rationale",
    --   "evidence": [{"filename", "excerpt"}]}]
    findings             jsonb       NOT NULL DEFAULT '[]',
    summary              text        NOT NULL DEFAULT '',
    created_at           timestamptz NOT NULL DEFAULT now(),
    completed_at         timestamptz
);

CREATE INDEX audits_owner_idx ON audits (owner_id, created_at DESC);
