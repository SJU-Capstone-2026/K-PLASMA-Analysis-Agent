ALTER TABLE agent_v2_model_attempt DROP CONSTRAINT agent_v2_model_attempt_kind_check;
ALTER TABLE agent_v2_model_attempt ADD CONSTRAINT agent_v2_model_attempt_kind_check
    CHECK (kind IN ('PLAN_INITIAL', 'REPLAN', 'PLAN_REVIEW', 'COMPOSE', 'ANSWER_REWRITE', 'PARTIAL_COMPOSE', 'REVIEW'));
