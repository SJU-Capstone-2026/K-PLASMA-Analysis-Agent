alter table agent_request add constraint agent_request_graph_version_check
    check (graph_version in ('v1', 'v2'));
alter table workspace add column agent_graph_version text
    check (agent_graph_version in ('v1', 'v2'));

update workspace w set agent_graph_version = 'v1'
where exists (select 1 from conversation_turn t where t.workspace_id = w.id)
   or exists (select 1 from agent_request r
              where r.workspace_epoch = w.workspace_epoch and r.conversation_epoch = w.conversation_epoch);
