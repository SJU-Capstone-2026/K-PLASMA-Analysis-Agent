CREATE TABLE run_iad_snapshot (
    run_version_id uuid PRIMARY KEY REFERENCES run_version(id) ON DELETE CASCADE,
    points jsonb NOT NULL CHECK (jsonb_typeof(points) = 'array' AND jsonb_array_length(points) > 0),
    compact_output jsonb NOT NULL CHECK (jsonb_typeof(compact_output) = 'object')
);
