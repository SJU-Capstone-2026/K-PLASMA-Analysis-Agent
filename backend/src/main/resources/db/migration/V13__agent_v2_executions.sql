create table agent_v2_plan_revision (
    request_id uuid not null references agent_request(id) on delete cascade,
    revision integer not null check (revision between 1 and 3),
    input_revision bigint not null,
    plan jsonb not null,
    primary key (request_id, revision)
);

create table agent_step_execution (
    id uuid primary key,
    request_id uuid not null references agent_request(id) on delete cascade,
    plan_revision integer not null,
    step_id text not null,
    claim_generation bigint not null,
    input_revision bigint not null,
    inputs jsonb not null,
    source_refs jsonb,
    result jsonb,
    unique (request_id, plan_revision, input_revision, step_id),
    foreign key (request_id, plan_revision) references agent_v2_plan_revision(request_id, revision) on delete cascade
);

create table agent_v2_model_attempt (
    id uuid primary key,
    request_id uuid not null references agent_request(id) on delete cascade,
    attempt_key text not null,
    kind text not null check (kind in ('PLAN_INITIAL', 'REPLAN', 'COMPOSE', 'ANSWER_REWRITE', 'PARTIAL_COMPOSE', 'REVIEW')),
    claim_generation bigint not null,
    input_revision bigint not null,
    deadline timestamptz not null,
    outcome jsonb,
    unique (request_id, attempt_key)
);
