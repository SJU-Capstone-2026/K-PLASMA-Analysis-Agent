-- Additive activation only. Existing v1/v2 requests and snapshots keep their contracts.
alter table agent_request drop constraint agent_request_graph_version_check;
alter table agent_request add constraint agent_request_graph_version_check
    check (graph_version in ('v1', 'v2', 'v3'));
alter table workspace drop constraint workspace_agent_graph_version_check;
alter table workspace add constraint workspace_agent_graph_version_check
    check (agent_graph_version in ('v1', 'v2', 'v3'));
alter table workspace_conversation add constraint workspace_conversation_graph_version_check
    check (agent_graph_version in ('v1', 'v2', 'v3'));

alter table agent_request add column v3_options jsonb;
alter table agent_request add constraint agent_request_v3_options_check check (
    (graph_version <> 'v3' and v3_options is null)
    or (graph_version = 'v3' and v3_options is not null
        and jsonb_typeof(v3_options) = 'object'
        and v3_options ?& array['rulesEnabled','ragEnabled','configDigest']
        and (jsonb_typeof(v3_options->'rulesEnabled') = 'boolean') is true
        and (jsonb_typeof(v3_options->'ragEnabled') = 'boolean') is true
        and (v3_options->>'configDigest' ~ '^[0-9a-f]{64}$') is true
        and (v3_options - array['rulesEnabled','ragEnabled','configDigest']) = '{}'::jsonb)
);
