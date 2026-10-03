CREATE TABLE run (
    run_id varchar(64) PRIMARY KEY,
    current_version_id uuid
);
CREATE TABLE run_version (
    id uuid PRIMARY KEY,
    registration_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    run_id varchar(64) NOT NULL REFERENCES run(run_id),
    source_id uuid NOT NULL REFERENCES source_set(id),
    registered_at timestamptz NOT NULL,
    summary jsonb NOT NULL,
    full_run jsonb NOT NULL
);
ALTER TABLE run ADD CONSTRAINT run_current_version_fk FOREIGN KEY (current_version_id) REFERENCES run_version(id);
CREATE INDEX run_version_source_idx ON run_version(source_id, registration_sequence);
ALTER TABLE import_job ADD COLUMN reprocess boolean NOT NULL DEFAULT false;
ALTER TABLE import_job ADD CONSTRAINT import_job_version_fk FOREIGN KEY (run_version_id) REFERENCES run_version(id);
CREATE TABLE reprocess_idempotency (
    idempotency_key varchar(200) PRIMARY KEY,
    original_job_id uuid NOT NULL REFERENCES import_job(id),
    batch_id uuid NOT NULL REFERENCES import_batch(id)
);
