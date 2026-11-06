CREATE TABLE run_output_snapshot (
    run_version_id uuid NOT NULL REFERENCES run_version(id) ON DELETE CASCADE,
    output_id text NOT NULL CHECK (output_id IN ('ied', 'iad', 'iead', 'current', 'potential', 'density', 'residual')),
    compact_output jsonb NOT NULL CHECK (jsonb_typeof(compact_output) = 'object'),
    display jsonb NOT NULL CHECK (jsonb_typeof(display) = 'object'),
    PRIMARY KEY (run_version_id, output_id)
);

INSERT INTO run_output_snapshot (run_version_id, output_id, compact_output, display)
SELECT run_version_id, 'iad', compact_output,
       jsonb_build_object('kind', 'line', 'samples', (
           SELECT jsonb_agg(jsonb_build_object('x', point->0, 'y', point->1) ORDER BY ordinal)
           FROM jsonb_array_elements(points) WITH ORDINALITY AS samples(point, ordinal)
       ), 'rows', '[]'::jsonb)
FROM run_iad_snapshot;
