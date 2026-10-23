-- ERD v6 sections 28 and 29: application publication rules and their change log (#132 list, #133 switch).
--
-- A rule is an application publication policy (AI owner, 2026-10-22, 5-A): it can only keep content that is already
-- publication-eligible off the public graph. It never publishes a HOLD, never turns a HOLD into an approval and never changes
-- an AI judgement input. Only an AI pass (inside a handoff) or an administrator allow followed by a new handoff publishes.
-- No rule is seeded here: the prototype's R1 (publish a HOLD without its unverified role) is not carried over, and the first
-- application rule is added by its own migration once the team and the AI owner agree on it.

CREATE TABLE publication_rules (
    id text PRIMARY KEY,
    title text NOT NULL,
    summary text NOT NULL,
    definition jsonb NOT NULL,
    default_enabled boolean NOT NULL,
    enabled boolean NOT NULL,
    revision bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL,
    -- The id carries the definition's version (`<ruleId>@<version>`): a changed definition is a new rule row.
    -- The same rule as PublicationRuleEvaluator.RULE_ID (com.zoop.graph.rules); a change to one must change the other.
    CONSTRAINT ck_publication_rules_id CHECK (id ~ '^[A-Za-z][A-Za-z0-9_-]{0,63}@[1-9][0-9]{0,8}$'),
    CONSTRAINT ck_publication_rules_title CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    CONSTRAINT ck_publication_rules_summary CHECK (length(btrim(summary)) BETWEEN 1 AND 1000),
    CONSTRAINT ck_publication_rules_definition_object CHECK (jsonb_typeof(definition) = 'object'),
    CONSTRAINT ck_publication_rules_revision CHECK (revision >= 0)
);

-- The definition is fixed with its id; only the switch, its revision and its time move, and the revision only forward by one.
CREATE FUNCTION publication_rules_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.title, NEW.summary, NEW.definition, NEW.default_enabled)
        IS DISTINCT FROM (OLD.id, OLD.title, OLD.summary, OLD.definition, OLD.default_enabled) THEN
        RAISE EXCEPTION 'publication rule definition is immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'publication rule revision moves by one per change' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER tr_publication_rules_guard BEFORE UPDATE ON publication_rules
    FOR EACH ROW EXECUTE FUNCTION publication_rules_guard_update();

-- One row per switch. `revision` is the rule's own (1, 2, ...); `log_revision` is the app-wide rule counter that graph versions
-- and briefings fix as `rule_revision`, taken as MAX+1 under the shared publication lock so commit order never inverts it.
-- A rule's initial state is its `default_enabled` with no change row.
CREATE TABLE publication_rule_changes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rule_id text NOT NULL,
    revision bigint NOT NULL,
    log_revision bigint NOT NULL,
    enabled boolean NOT NULL,
    reason text NOT NULL,
    admin_id text NOT NULL,
    admin_email_snapshot text NOT NULL,
    changed_at timestamptz NOT NULL,
    CONSTRAINT fk_publication_rule_changes_rule FOREIGN KEY (rule_id) REFERENCES publication_rules (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_publication_rule_changes_admin FOREIGN KEY (admin_id) REFERENCES admins (id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT uq_publication_rule_changes_revision UNIQUE (rule_id, revision),
    CONSTRAINT uq_publication_rule_changes_log_revision UNIQUE (log_revision),
    CONSTRAINT ck_publication_rule_changes_revisions CHECK (revision >= 1 AND log_revision >= 1),
    CONSTRAINT ck_publication_rule_changes_reason CHECK (length(btrim(reason)) BETWEEN 1 AND 500)
);

-- The change log is history: it is appended to, never rewritten.
CREATE FUNCTION publication_rule_changes_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'publication rule changes are append-only' USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER tr_publication_rule_changes_guard BEFORE UPDATE OR DELETE ON publication_rule_changes
    FOR EACH ROW EXECUTE FUNCTION publication_rule_changes_guard();
