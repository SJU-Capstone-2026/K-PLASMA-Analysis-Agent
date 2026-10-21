-- Keyset ordering and selected-only reads; reverse scans also support descending order.
CREATE INDEX agent_run_selection_page_idx
    ON agent_run_selection_option USING btree (snapshot_id, natural_sort_key, run_id, run_version_id);
CREATE INDEX agent_run_selection_selected_idx
    ON agent_run_selection_option USING btree (snapshot_id, ordinal)
    WHERE selected;

-- Preserve arbitrary literal substring search instead of changing it to prefix search.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX agent_run_selection_search_idx
    ON agent_run_selection_option USING gin (search_text gin_trgm_ops);
