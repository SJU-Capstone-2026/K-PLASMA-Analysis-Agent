-- Lists now read the current catalogue. Only attached/selected exact versions are request-owned.
ALTER TABLE agent_run_selection ADD COLUMN alias_base bigint NOT NULL DEFAULT 0;
ALTER TABLE agent_run_selection_option ADD COLUMN attached boolean NOT NULL DEFAULT false;
UPDATE agent_run_selection s SET alias_base=coalesce((SELECT max(substring(o.alias from 2)::bigint)
    FROM agent_run_selection_option o WHERE o.snapshot_id=s.id AND o.alias ~ '^R[0-9]{1,18}$'),0);
UPDATE agent_run_selection_option o SET attached=true FROM agent_run_selection s,agent_request r
    WHERE s.id=o.snapshot_id AND r.id=s.request_id AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(coalesce(r.context_snapshot->'comparisonReference'->'entries','[]'::jsonb)) e
      WHERE e->'ref'->>'runVersionId'=o.run_version_id::text AND e->>'key'=o.alias);
DELETE FROM agent_run_selection_option WHERE NOT selected AND NOT attached;
ALTER TABLE agent_run_selection DROP COLUMN total_count;
DROP INDEX agent_run_selection_page_idx;
DROP INDEX agent_run_selection_search_idx;

-- Shared search/order values belong to original rows, not a per-picker catalogue copy.
ALTER TABLE run ADD COLUMN picker_sort_key text COLLATE run_selection_natural
    GENERATED ALWAYS AS (lower(run_id)) STORED;
ALTER TABLE run_version ADD COLUMN picker_search_text text GENERATED ALWAYS AS
    (run_selection_search_v1('',run_id,id,run_selection_conditions_v1(summary))) STORED;
