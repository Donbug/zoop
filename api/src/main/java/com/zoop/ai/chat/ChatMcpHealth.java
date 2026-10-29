package com.zoop.ai.chat;

/**
 * The content-free MCP preflight answer from {@code GET /internal/v1/chat-mcp-health}. An unreachable answer is a
 * connection observation; a thrown AI client exception is a probe/service failure and is deliberately not normalized into
 * one.
 */
public record ChatMcpHealth(boolean reachable, Reason reason) {
    public enum Reason { TIMEOUT, CONNECT_FAILED, STATUS_UNEXPECTED }

    public ChatMcpHealth {
        if (reachable == (reason != null)) {
            throw new IllegalArgumentException("an unreachable MCP endpoint has a reason and a reachable one none");
        }
    }
}
