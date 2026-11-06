create table workspace_conversation (
    workspace_epoch bigint not null,
    conversation_epoch bigint not null,
    active_run jsonb,
    candidate_reference jsonb,
    agent_graph_version varchar(24),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (workspace_epoch, conversation_epoch)
);

insert into workspace_conversation(workspace_epoch, conversation_epoch, active_run, candidate_reference, agent_graph_version)
select workspace_epoch, conversation_epoch, active_run, candidate_reference, agent_graph_version from workspace;

alter table conversation_turn add column workspace_epoch bigint;
alter table conversation_turn add column conversation_epoch bigint;
update conversation_turn t set workspace_epoch=w.workspace_epoch, conversation_epoch=w.conversation_epoch
from workspace w where t.workspace_id=w.id;
alter table conversation_turn alter column workspace_epoch set not null;
alter table conversation_turn alter column conversation_epoch set not null;
alter table conversation_turn add foreign key (workspace_epoch, conversation_epoch)
    references workspace_conversation(workspace_epoch, conversation_epoch) on delete cascade;
create index conversation_turn_room_idx on conversation_turn(workspace_epoch, conversation_epoch, ordinal);
