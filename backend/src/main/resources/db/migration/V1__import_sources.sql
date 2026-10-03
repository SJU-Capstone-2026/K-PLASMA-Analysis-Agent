CREATE TABLE import_batch (
    id uuid PRIMARY KEY,
    status varchar(32) NOT NULL,
    received_bytes bigint NOT NULL CHECK (received_bytes >= 0),
    total_bytes bigint NOT NULL CHECK (total_bytes >= 0),
    processed_runs integer NOT NULL DEFAULT 0,
    total_runs integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE source_set (
    id uuid PRIMARY KEY,
    sha256 char(64) NOT NULL UNIQUE,
    total_bytes bigint NOT NULL CHECK (total_bytes >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE source_file (
    source_id uuid NOT NULL REFERENCES source_set(id),
    relative_path varchar(1024) NOT NULL,
    kind varchar(32) NOT NULL,
    size bigint NOT NULL CHECK (size >= 0),
    sha256 char(64) NOT NULL,
    storage_path varchar(1200) NOT NULL,
    PRIMARY KEY (source_id, relative_path)
);
CREATE TABLE import_job (
    id uuid PRIMARY KEY,
    batch_id uuid NOT NULL REFERENCES import_batch(id),
    source_id uuid NOT NULL REFERENCES source_set(id),
    source_root varchar(1024) NOT NULL,
    run_id varchar(64),
    run_version_id uuid,
    status varchar(32) NOT NULL,
    reason text,
    errors jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX import_job_batch_idx ON import_job(batch_id, created_at, id);
CREATE INDEX import_job_status_idx ON import_job(status, created_at);
-- Complete upload lineage, including ancillary files outside a discovered Run and OS metadata.
-- Multiple batches may point at the same immutable original source file.
CREATE TABLE import_batch_file (
    batch_id uuid NOT NULL REFERENCES import_batch(id),
    relative_path varchar(1024) NOT NULL,
    size bigint NOT NULL CHECK (size >= 0),
    sha256 char(64) NOT NULL,
    kind varchar(32) NOT NULL,
    storage_path varchar(1200) NOT NULL,
    PRIMARY KEY (batch_id, relative_path)
);
CREATE TABLE import_idempotency (
    idempotency_key varchar(200) PRIMARY KEY,
    request_hash char(64) NOT NULL,
    batch_id uuid NOT NULL REFERENCES import_batch(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
