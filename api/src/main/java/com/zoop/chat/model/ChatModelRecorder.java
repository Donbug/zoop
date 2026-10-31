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
    public String start(String jobId, int attemptNo, String stage, String mode) {
        String id = "aix-chat-" + UUID.randomUUID();
        jdbc.update("""
                INSERT INTO ai_executions (id, feature, execution_mode, status, chat_job_id, attempt_no, stage, started_at)
                VALUES (:id, 'chatbot', :mode, 'running', :job, :attempt, :stage, :at)
                """, new MapSqlParameterSource("id", id).addValue("mode", mode).addValue("job", jobId)
                .addValue("attempt", attemptNo).addValue("stage", stage).addValue("at", Timestamp.from(clock.instant())));
        return id;
    }

    /** {@code status} is {@code succeeded}, {@code failed} or {@code unknown}; the receipt and error code may be null. */
    public void finish(String id, String status, String sendState, ChatStageReply.Receipt receipt, String errorCode) {
        jdbc.update("""
                UPDATE ai_executions SET status = :status, provider_send_state = :send_state,
                       provider_revision = :provider_revision, receipt_execution_mode = :receipt_mode,
                       provider_sent_at = :sent_at, provider_received_at = :received_at,
                       provider = :provider, model = :model,
                       prompt_version = :prompt, input_tokens = :input, output_tokens = :output,
                       reasoning_tokens = :reasoning,
                       error_code = :error, finished_at = :at
                WHERE id = :id AND status = 'running'
                """, new MapSqlParameterSource("id", id).addValue("status", status).addValue("send_state", sendState)
                .addValue("provider_revision", receipt == null ? null : receipt.providerRevision())
                .addValue("receipt_mode", receipt == null ? null : receipt.executionMode())
                .addValue("sent_at", receipt == null || receipt.sentAt() == null ? null : Timestamp.from(receipt.sentAt()))
                .addValue("received_at", receipt == null || receipt.receivedAt() == null ? null : Timestamp.from(receipt.receivedAt()))
                .addValue("provider", receipt == null ? null : receipt.provider())
                .addValue("model", receipt == null ? null : receipt.model())
                .addValue("prompt", receipt == null ? null : receipt.promptVersion())
                .addValue("input", receipt == null ? null : receipt.inputTokens())
                .addValue("output", receipt == null ? null : receipt.outputTokens())
                .addValue("reasoning", receipt == null ? null : receipt.reasoningTokens())
                .addValue("error", errorCode).addValue("at", Timestamp.from(clock.instant())));
    }
}
