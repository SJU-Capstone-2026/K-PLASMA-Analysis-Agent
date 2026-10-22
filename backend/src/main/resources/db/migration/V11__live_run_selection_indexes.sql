CREATE INDEX run_picker_order_idx ON run USING btree (picker_sort_key,run_id,current_version_id)
    WHERE current_version_id IS NOT NULL;
CREATE INDEX run_version_picker_search_idx ON run_version USING gin (picker_search_text gin_trgm_ops);
