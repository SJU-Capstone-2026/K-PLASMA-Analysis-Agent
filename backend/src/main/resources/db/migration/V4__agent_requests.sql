-- Durable v1 work is accepted before any model call; all runtime identities are fenced.
CREATE TABLE agent_request (
    id uuid PRIMARY KEY,
    workspace_epoch bigint NOT NULL,
    conversation_epoch bigint NOT NULL,
    request_revision bigint NOT NULL DEFAULT 0,
    claim_generation bigint NOT NULL DEFAULT 0,
    status varchar(24) NOT NULL CHECK(status IN ('QUEUED','RUNNING','NEEDS_INPUT','COMPLETED','FAILED','CANCELLED')),
    stage varchar(80) NOT NULL DEFAULT 'queued',
    graph_version varchar(24) NOT NULL DEFAULT 'v1',
    question text,
    submission jsonb,
    context_snapshot jsonb,
    manifest jsonb,
    operation_kind varchar(40),
    depends_on_context boolean NOT NULL DEFAULT true,
    worker_id varchar(200),
    lease_until timestamptz,
    pending_input jsonb,
    error jsonb,
    partial_result jsonb,
    final_answer jsonb,
    turn_id uuid,
    attempts jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_request_queue_idx ON agent_request(status,lease_until,created_at);
CREATE INDEX agent_request_workspace_idx ON agent_request(workspace_epoch,conversation_epoch,created_at DESC);
CREATE UNIQUE INDEX agent_request_active_idx ON agent_request(workspace_epoch,conversation_epoch)
    WHERE status IN ('QUEUED','RUNNING','NEEDS_INPUT');
CREATE TABLE agent_input_event (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES agent_request(id) ON DELETE CASCADE,
    request_revision bigint NOT NULL,
    idempotency_key varchar(200) NOT NULL,
    pending_input_id varchar(200) NOT NULL,
    input jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(request_id,idempotency_key),
    UNIQUE(request_id,request_revision)
);
