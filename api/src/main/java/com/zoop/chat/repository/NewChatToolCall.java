package com.zoop.chat.repository;

/**
 * A reserved {@code chat_tool_calls} row (ERD v6 §36): the registry values fixed at planning time, the digest of the
 * allowed request structure and its metadata ({@code requestMeta}, a JSON object without member ids or question text).
 */
public record NewChatToolCall(String id, String jobId, int attemptNo, int planRevision, int callIndex, String toolCallId,
        String registryVersion, String registryGroup, String capabilityId, String toolId, String schemaVersion,
        String inputDigest, String requestMeta) { }
