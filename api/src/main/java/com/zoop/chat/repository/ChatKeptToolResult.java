package com.zoop.chat.repository;

/** A succeeded MCP call with its server-owned reservation and the exact normalized result delivered to the model. */
public record ChatKeptToolResult(String jobId, String memberId, int attemptNo, String toolCallId, String capabilityId,
        String requestMeta, String inputDigest, String result) { }
