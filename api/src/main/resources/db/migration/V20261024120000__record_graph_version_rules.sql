-- ERD v6 sections 24 and 29: the publication rules an imported graph version was filtered with (#133), and the first two rules.
--
-- An import reads the enabled rules, `rule_revision` (MAX publication_rule_changes.log_revision) and `review_revision`
-- (MAX review_decisions.global_revision) in ONE statement, without the publication lock: imports run every round, and both counters
-- are taken as MAX+1 under that lock, so one statement always sees a committed prefix of each. The version keeps those two numbers
-- and, here, the exact rules it applied, so a repeated import of the same pins filters with the same rules even after a switch.
-- A version staged before rules existed (rule_revision NULL) has no row here and was not filtered.

CREATE TABLE graph_version_rules (
    graph_version_id text NOT NULL,
    rule_id text NOT NULL,
    CONSTRAINT pk_graph_version_rules PRIMARY KEY (graph_version_id, rule_id),
    -- The rows belong to their version: they go only with it (graph_versions itself has no delete guard).
    CONSTRAINT fk_graph_version_rules_version FOREIGN KEY (graph_version_id) REFERENCES graph_versions (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_graph_version_rules_rule FOREIGN KEY (rule_id) REFERENCES publication_rules (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- What a version was filtered with is part of the version: written with it, never rewritten.
CREATE FUNCTION graph_version_rules_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'graph version rules are written once' USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER tr_graph_version_rules_guard BEFORE UPDATE ON graph_version_rules
    FOR EACH ROW EXECUTE FUNCTION graph_version_rules_guard();

-- The two rules of docs/development/issue-133-publication-rules.md section 1. Both start OFF: the rules doc proposes
-- single-source@1 on, but its source count is a team decision and is shared with the AI owner first (rules doc section 3), and
-- imports run every round, so an ON default would hide single-source relations from the first round after deploy. Turning one on
-- is an administrator switch (setPublicationRule) or, once agreed, a later migration that changes nothing here (a new id).
INSERT INTO publication_rules (id, title, summary, definition, default_enabled, enabled, revision, updated_at) VALUES
    ('single-source@1', '출처가 기사 1개뿐인 관계 숨기기',
     '근거 기사(구조 관계는 basis 기사 포함)가 서로 다른 기사 2개 미만인 INVOLVES·STRUCTURALLY_RELATED_TO 관계를 공개 그래프에서 숨깁니다. 같은 기사의 여러 버전은 1건으로 셉니다.',
     '{"kind": "single_source", "minSources": 2, "relationTypes": ["INVOLVES", "STRUCTURALLY_RELATED_TO"]}', false, false, 0,
     statement_timestamp()),
    ('speculative-issue@1', '취소·전망 이슈 숨기기',
     'assertionStatus가 cancelled 또는 forecast인 이슈와 그 관계·FOLLOWS를 공개 그래프에서 숨깁니다.',
     '{"kind": "assertion_status", "hide": ["cancelled", "forecast"]}', false, false, 0, statement_timestamp());
