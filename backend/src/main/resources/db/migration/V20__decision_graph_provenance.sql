-- Internal provenance is not part of the saved decision's public JSON.
alter table decision add column origin_graph_version varchar(24) default 'v1'
    check (origin_graph_version in ('v1', 'v2', 'v3', 'v2_localLLM'));

-- Unresolved source-linked history is not safe to disclose to a cloud worker.
update decision set origin_graph_version=null
where record->'source' is not null and record->'source'<>'null'::jsonb;

update decision d set origin_graph_version=t.snapshot#>>'{answerSnapshot,graphVersion}'
from conversation_turn t
where t.id::text=d.record#>>'{source,turnId}'
    and t.snapshot#>>'{answerSnapshot,graphVersion}' in ('v2','v3','v2_localLLM')
    and t.snapshot#>>'{answerSnapshot,implementationId}'=t.snapshot#>>'{answerSnapshot,graphVersion}'
    and not exists(select 1 from agent_request r where r.turn_id=t.id
        and r.graph_version<>t.snapshot#>>'{answerSnapshot,graphVersion}');
