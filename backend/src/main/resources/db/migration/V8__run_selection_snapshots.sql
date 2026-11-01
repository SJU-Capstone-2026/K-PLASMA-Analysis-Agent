-- Temporary, request-scoped picker data. Original Run versions may be deleted.
CREATE COLLATION run_selection_natural (provider = icu, locale = 'und-u-kn-true', deterministic = true);
CREATE TABLE agent_run_selection (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES agent_request(id) ON DELETE CASCADE,
    pending_input_id varchar(200) NOT NULL,
    revision bigint NOT NULL DEFAULT 0,
    baseline_key varchar(80),
    total_count bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (request_id, pending_input_id)
);
CREATE TABLE agent_run_selection_option (
    snapshot_id uuid NOT NULL REFERENCES agent_run_selection(id) ON DELETE CASCADE,
    alias varchar(80) NOT NULL,
    ordinal bigint NOT NULL,
    run_id varchar(64) NOT NULL,
    run_version_id uuid NOT NULL,
    conditions jsonb NOT NULL,
    selectable boolean NOT NULL,
    unavailable_reason text,
    selected boolean NOT NULL DEFAULT false,
    natural_sort_key text COLLATE run_selection_natural NOT NULL,
    search_text text NOT NULL,
    PRIMARY KEY (snapshot_id, alias),
    UNIQUE (snapshot_id, run_version_id)
);
CREATE TABLE agent_run_selection_mutation (
    snapshot_id uuid NOT NULL REFERENCES agent_run_selection(id) ON DELETE CASCADE,
    idempotency_key varchar(200) NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (snapshot_id, idempotency_key)
);

CREATE FUNCTION run_selection_conditions_v1(summary jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT jsonb_object_agg(field,jsonb_build_object(
        'value',CASE WHEN jsonb_typeof(summary->field)='number' THEN to_jsonb(trim_scale((summary->>field)::numeric)) ELSE 'null'::jsonb END,
        'unit',coalesce(summary->'units'->>field,CASE WHEN field='pressure' THEN 'mTorr' ELSE 'W' END),
        'status',CASE WHEN jsonb_typeof(summary->field)='number' THEN 'AVAILABLE' ELSE 'UNAVAILABLE' END,
        'reason',CASE WHEN jsonb_typeof(summary->field)='number' THEN NULL ELSE 'MISSING_VALUE' END,
        'sourceValue',NULL)) FROM unnest(ARRAY['pressure','sourcePower','biasPower']) field
$$;
CREATE FUNCTION run_selection_search_v1(alias text, run_id text, version_id uuid, conditions jsonb) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT lower(concat_ws(' ',alias,run_id,version_id::text,
        coalesce(conditions->'pressure'->>'value','null'),conditions->'pressure'->>'unit',
        coalesce(conditions->'sourcePower'->>'value','null'),conditions->'sourcePower'->>'unit',
        coalesce(conditions->'biasPower'->>'value','null'),conditions->'biasPower'->>'unit'))
$$;
