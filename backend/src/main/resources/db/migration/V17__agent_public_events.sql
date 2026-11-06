-- Existing requests have no trustworthy duration. Only new requests start at zero.
alter table agent_request add column running_duration_ms bigint;
alter table agent_request alter column running_duration_ms set default 0;
alter table agent_request add column running_started_at timestamptz;
alter table agent_request add column execution_finished_at timestamptz;
alter table agent_request add column last_public_event_seq bigint not null default 0;
alter table agent_request add column public_answer_revision bigint not null default 0;
alter table agent_request add column public_stream_id varchar(200);
alter table agent_request add column public_chunk_index bigint;
alter table agent_request add column public_preview_chars integer not null default 0;

create table agent_public_event (
    request_id uuid not null references agent_request(id) on delete cascade,
    seq bigint not null check(seq > 0),
    event_key varchar(200) not null,
    request_revision bigint not null,
    type varchar(40) not null check(type in ('activity','results.ready','answer.start','answer.delta','answer.reset','request.state')),
    payload jsonb not null,
    input_payload jsonb not null,
    occurred_at timestamptz not null default clock_timestamp(),
    primary key(request_id,seq),
    unique(request_id,event_key)
);
