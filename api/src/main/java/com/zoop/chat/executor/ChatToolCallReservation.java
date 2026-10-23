package com.zoop.chat.executor;

/**
 * One call of a confirmed tool plan, as {@code chat_tool_calls} records it: the registry values at planning time and the
 * allowed request structure ({@code requestMeta}, a JSON object) with its digest.
 */
public record ChatToolCallReservation(String registryVersion, String registryGroup, String capabilityId, String toolId,
        String schemaVersion, String inputDigest, String requestMeta) { }
