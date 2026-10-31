package com.zoop.ai.chat;

import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

import tools.jackson.databind.JsonNode;

/**
 * One stage request. {@code invocationId} names one stage of one job attempt and doubles as the Idempotency-Key; {@code input} is
 * the stage input of the {@code zoop-ai-chat-3} contract, which the AI service validates completely.
 */
public record ChatStageCall(String invocationId, String stage, String mode, JsonNode input) {
    public static final Set<String> STAGES = Set.of("chat-router", "chat-answer", "chat-verification", "chat-agent");
    private static final Pattern INVOCATION = Pattern.compile("[A-Za-z0-9_.:-]{8,96}");

    public ChatStageCall {
        Objects.requireNonNull(input, "input");
        if (invocationId == null || !INVOCATION.matcher(invocationId).matches()) {
            throw new IllegalArgumentException("invocation id must match [A-Za-z0-9_.:-]{8,96}");
        }
        if (!STAGES.contains(stage)) throw new IllegalArgumentException("unknown chat stage");
        if (!"replay".equals(mode) && !"live".equals(mode)) throw new IllegalArgumentException("mode is replay or live");
        if (!input.isObject()) throw new IllegalArgumentException("stage input is an object");
    }
}
