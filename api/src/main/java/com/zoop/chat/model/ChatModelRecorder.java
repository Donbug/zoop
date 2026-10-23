package com.zoop.chat.model;

import java.sql.Timestamp;
import java.time.Clock;
import java.util.UUID;

import com.zoop.ai.chat.ChatStageReply;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/**
 * Records each chatbot model stage in {@code ai_executions} (ERD v6, {@code feature=chatbot}, owned by the chat job): a
 * {@code running} row before the request is handed to the AI service, then its end. {@code unknown} is a stage whose fate is
 * unknown. Each write commits on its own, so the record survives a run that is cut off afterwards.
 */
public class ChatModelRecorder {
    private final NamedParameterJdbcTemplate jdbc;
    private final Clock clock;

    public ChatModelRecorder(NamedParameterJdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    /** The new execution id. */
    public String start(String jobId, String stage, String mode) {
        String id = "aix-chat-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO ai_executions (id, feature, execution_mode, status, chat_job_id, stage, started_at)
                VALUES (:id, 'chatbot', :mode, 'running', :job, :stage, :at)
                """, new MapSqlParameterSource("id", id).addValue("mode", mode).addValue("job", jobId)
                .addValue("stage", stage).addValue("at", Timestamp.from(clock.instant())));
        return id;
    }

    /** {@code status} is {@code succeeded}, {@code failed} or {@code unknown}; the receipt and error code may be null. */
    public void finish(String id, String status, ChatStageReply.Receipt receipt, String errorCode) {
        jdbc.update("""
                UPDATE ai_executions SET status = :status, provider = :provider, model = :model,
                       prompt_version = :prompt, input_tokens = :input, output_tokens = :output,
                       error_code = :error, finished_at = :at
                WHERE id = :id AND status = 'running'
                """, new MapSqlParameterSource("id", id).addValue("status", status)
                .addValue("provider", receipt == null ? null : receipt.provider())
                .addValue("model", receipt == null ? null : receipt.model())
                .addValue("prompt", receipt == null ? null : receipt.promptVersion())
                .addValue("input", receipt == null ? null : receipt.inputTokens())
                .addValue("output", receipt == null ? null : receipt.outputTokens())
                .addValue("error", errorCode).addValue("at", Timestamp.from(clock.instant())));
    }
}
