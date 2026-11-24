alter table agent_request drop constraint agent_request_graph_version_check;
alter table agent_request add constraint agent_request_graph_version_check
    check (graph_version in ('v1', 'v2', 'v3', 'v2_localLLM'));

alter table workspace drop constraint workspace_agent_graph_version_check;
alter table workspace add constraint workspace_agent_graph_version_check
    check (agent_graph_version in ('v1', 'v2', 'v3', 'v2_localLLM'));

alter table workspace_conversation add constraint workspace_conversation_agent_graph_version_check
    check (agent_graph_version in ('v1', 'v2', 'v3', 'v2_localLLM'));
