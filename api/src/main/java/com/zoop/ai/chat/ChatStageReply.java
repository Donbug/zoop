package com.zoop.ai.chat;

import java.time.Instant;

import tools.jackson.databind.JsonNode;

/**
 * The stage outcome. {@code answer} is the typed stage answer when {@code succeeded}, still untrusted: the orchestrator checks it.
 * {@code receipt} is present once a request was sent.
 */
public record ChatStageReply(String invocationId, String stage, boolean succeeded, JsonNode answer, Failure failure,
        Receipt receipt, JsonNode resourceBinding) {

    /** {@code sent}: a request left the AI runtime. {@code unknown}: sent and its fate is unknown; never send it again. */
    public record Failure(String code, boolean sent, boolean unknown) {
        public FailureCategory category() {
            return sent ? FailureCategory.forCode(code) : FailureCategory.CONTRACT;
        }
    }

    /** Protocol/resource refusals cannot stand in for a semantic-verification outcome. */
    public enum FailureCategory {
        MODEL, CONTRACT;

        public static FailureCategory forCode(String code) {
            if (code == null) return MODEL;
            return code.startsWith("chat_resource_") || switch (code) {
                case "invalid_request", "request_invalid", "service_configuration_invalid", "chat_runtime_contract_mismatch",
                        "chat_legacy_effort_configuration", "input_budget_exceeded", "output_budget_exceeded",
                        "chat_budget_exhausted", "provider_usage_invalid", "agent_context_unavailable" -> true;
                default -> false;
            } ? CONTRACT : MODEL;
        }
    }

    /** Who received the request and what they reported; token counts are null when not reported. {@code outputTokens} includes {@code reasoningTokens}. */
    public record Receipt(String provider, String providerRevision, String model, String promptVersion, String executionMode,
            Long inputTokens, Long outputTokens, Long reasoningTokens, Instant sentAt, Instant receivedAt) { }
}
