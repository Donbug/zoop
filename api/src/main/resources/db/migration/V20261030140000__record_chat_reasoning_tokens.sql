-- D-AI-02: keep the reasoning tokens a model stage reports. They are part of output_tokens, and the answer length limit of
-- the live spike (2k) is the output without them, so the ledger alone can show it.
ALTER TABLE ai_executions ADD COLUMN reasoning_tokens bigint;
ALTER TABLE ai_executions ADD CONSTRAINT ck_ai_executions_reasoning_tokens
    CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0);
