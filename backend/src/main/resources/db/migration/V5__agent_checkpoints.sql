-- The worker has no database credentials. Spring writes an opaque, typed JSON/base64
-- checkpoint and its pending writes in the same transaction as the claim row lock.
-- This custom synchronous saver replaces direct worker SQL and a SECURITY DEFINER role.
CREATE TABLE agent_checkpoint (
    request_id uuid PRIMARY KEY REFERENCES agent_request(id) ON DELETE CASCADE,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
