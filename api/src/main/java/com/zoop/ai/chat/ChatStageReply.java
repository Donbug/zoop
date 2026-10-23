package com.zoop.ai.chat;

import java.time.Instant;

import tools.jackson.databind.JsonNode;

/**
 * The stage outcome. {@code answer} is the typed stage answer when {@code succeeded}, still untrusted: the orchestrator checks it.
 * {@code receipt} is present once a request was sent.
 */
public record ChatStageReply(String invocationId, String stage, boolean succeeded, JsonNode answer, Failure failure,
        Receipt receipt) {

    /** {@code sent}: a request left the AI runtime. {@code unknown}: sent and its fate is unknown; never send it again. */
    public record Failure(String code, boolean sent, boolean unknown) { }

    /** Who received the request and what they reported; token counts are null when not reported. */
    public record Receipt(String provider, String providerRevision, String model, String promptVersion, String executionMode,
            Long inputTokens, Long outputTokens, Instant sentAt, Instant receivedAt) { }
}
