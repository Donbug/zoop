-- D-AI-02 live spike: the content-free ledger of the named chat jobs, input of scripts/chat_live_spike_extract.py.
-- Selects status, times, counts and revisions only: never a question, result, grant, owner token or free-form message.
--   psql "$DB" -At -v ON_ERROR_STOP=1 -v jobs='job-a,job-b' -f scripts/chat_live_spike_ledger.sql > ledger.json
SELECT COALESCE(json_agg(row_to_json(l) ORDER BY l.job_id), '[]')
FROM (
    SELECT j.id AS job_id,
           j.status,
           COALESCE(j.failure ->> 'reason', j.failure ->> 'kind') AS failure_code,
           jsonb_array_length(j.attempts) AS attempts,
           last.attempt ->> 'mode' AS attempt_mode,
           last.attempt ->> 'startedAt' AS started_at,
           to_char(j.finished_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS finished_at,
           j.route_summary ->> 'path' AS path,
           (j.route_summary ->> 'approvedCalls')::integer AS approved_calls,
           (j.route_summary ->> 'deniedCalls')::integer AS denied_calls,
           calls.tool_calls,
           calls.web_calls,
           calls.registry_versions,
           stages.stages
    FROM chat_jobs j
    CROSS JOIN LATERAL (
        SELECT a AS attempt FROM jsonb_array_elements(j.attempts) a ORDER BY (a ->> 'n')::integer DESC LIMIT 1
    ) last
    CROSS JOIN LATERAL (
        SELECT count(*) FILTER (WHERE c.status <> 'cancelled') AS tool_calls,
               count(*) FILTER (WHERE c.status <> 'cancelled' AND c.capability_id = 'web.search') AS web_calls,
               COALESCE(json_agg(DISTINCT c.registry_version), '[]') AS registry_versions
        FROM chat_tool_calls c
        WHERE c.chat_job_id = j.id AND c.attempt_no = (last.attempt ->> 'n')::integer
    ) calls
    CROSS JOIN LATERAL (
        SELECT COALESCE(json_agg(json_build_object(
                   'stage', e.stage, 'status', e.status, 'sendState', e.provider_send_state,
                   'mode', e.receipt_execution_mode, 'model', e.model, 'promptVersion', e.prompt_version,
                   'inputTokens', e.input_tokens, 'outputTokens', e.output_tokens, 'reasoningTokens', e.reasoning_tokens
               ) ORDER BY e.started_at, e.id), '[]') AS stages
        FROM ai_executions e
        WHERE e.chat_job_id = j.id AND e.attempt_no = (last.attempt ->> 'n')::integer
    ) stages
    WHERE j.id = ANY (string_to_array(:'jobs', ','))
) l;
