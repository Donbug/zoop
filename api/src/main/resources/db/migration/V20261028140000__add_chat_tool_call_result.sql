-- The normalized result an MCP tool call returned to the model (ZOOP-AIG-001 v0.11, api/docs/chat-mcp.md).
-- The model reads it on the provider's side; the application keeps the same result so its deterministic checks (citations,
-- map targets, coverage) judge the final answer against exactly what the model received. Only a succeeded call keeps one,
-- written with its fenced end, and never more than one result's size limit (256 KiB). Server-planned (direct) calls keep none:
-- their results stay in the run that read them.
ALTER TABLE chat_tool_calls ADD COLUMN result jsonb;

ALTER TABLE chat_tool_calls ADD CONSTRAINT ck_chat_tool_calls_result CHECK (
    result IS NULL OR (jsonb_typeof(result) = 'object' AND status = 'succeeded' AND octet_length(result::text) <= 262144));
