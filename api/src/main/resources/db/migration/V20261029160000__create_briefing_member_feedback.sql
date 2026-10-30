-- FS066-01/02. Additive member feedback; anonymous local-preview SQLite is never imported as a member vote.
CREATE TABLE briefing_feedback (
    id text PRIMARY KEY,
    member_id text NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    feature text NOT NULL CHECK(feature IN ('briefing_round','briefing_issue')),
    target_id text NOT NULL CHECK(btrim(target_id)<>''),
    target_version text NOT NULL CHECK(btrim(target_version)<>''),
    round_id text NOT NULL REFERENCES briefing_rounds(id) ON DELETE RESTRICT,
    event_id text,
    value text NOT NULL CHECK(value IN ('up','down','none')),
    reason text CHECK(reason IS NULL OR (value='down' AND char_length(reason)<=200)),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK(updated_at>=created_at),
    CHECK((feature='briefing_round' AND event_id IS NULL AND target_id=round_id)
       OR (feature='briefing_issue' AND event_id IS NOT NULL AND target_id=round_id||'/'||event_id)),
    UNIQUE(member_id,feature,target_id)
);
CREATE INDEX ix_briefing_feedback_updated ON briefing_feedback(updated_at DESC,id DESC);
CREATE INDEX ix_briefing_feedback_round ON briefing_feedback(round_id);
