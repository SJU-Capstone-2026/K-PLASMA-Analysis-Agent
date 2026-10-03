-- A single local workspace serializes mutations. Its lifetime never owns Run or source rows.
CREATE TABLE workspace (
    id integer PRIMARY KEY CHECK (id = 1),
    workspace_epoch bigint NOT NULL CHECK (workspace_epoch > 0),
    conversation_epoch bigint NOT NULL CHECK (conversation_epoch > 0),
    revision bigint NOT NULL CHECK (revision >= 0),
    active_run jsonb,
    candidate_reference jsonb
);
INSERT INTO workspace(id, workspace_epoch, conversation_epoch, revision) VALUES (1, 1, 1, 0);
CREATE TABLE conversation_turn (
    id uuid PRIMARY KEY,
    workspace_id integer NOT NULL REFERENCES workspace(id),
    ordinal bigint GENERATED ALWAYS AS IDENTITY,
    snapshot jsonb NOT NULL,
    ui jsonb NOT NULL
);
CREATE INDEX conversation_turn_order_idx ON conversation_turn(workspace_id, ordinal);
CREATE TABLE decision (
    review_id varchar(200) PRIMARY KEY,
    workspace_id integer NOT NULL REFERENCES workspace(id),
    ordinal bigint GENERATED ALWAYS AS IDENTITY,
    record jsonb NOT NULL
);
CREATE INDEX decision_order_idx ON decision(workspace_id, ordinal DESC);
-- Keys remain scoped to the epochs that accepted them. A reset cannot revive an old request.
CREATE TABLE workspace_idempotency (
    workspace_epoch bigint NOT NULL,
    conversation_epoch bigint NOT NULL,
    scope varchar(16) NOT NULL,
    idempotency_key varchar(200) NOT NULL,
    payload jsonb NOT NULL,
    result_id varchar(200) NOT NULL,
    PRIMARY KEY (workspace_epoch, conversation_epoch, scope, idempotency_key)
);
