package com.zoop.chat.repository;

import java.util.List;

/**
 * How a started tool call ended: {@code succeeded} with what the result reported, or {@code failed} with an error code.
 * {@code evidenceIds} are the evidence ids the result passed on as answer candidates. {@code result}, only for a succeeded
 * MCP call, is the normalized result envelope (JSON) the model received, kept so the server checks the final answer against
 * exactly it ({@code chat_tool_calls.result}); null otherwise.
 */
public record ChatToolCallEnd(String status, String errorCode, String dataVersion, List<String> evidenceIds,
        Boolean truncated, Boolean nextAllowed, String result) {
    public ChatToolCallEnd {
        if (!"succeeded".equals(status) && !"failed".equals(status)) {
            throw new IllegalArgumentException("a started tool call ends succeeded or failed: " + status);
        }
        if ("failed".equals(status) == (errorCode == null)) {
            throw new IllegalArgumentException("only a failed tool call has an error code");
        }
        if (result != null && !"succeeded".equals(status)) {
            throw new IllegalArgumentException("only a succeeded tool call keeps a result");
        }
        evidenceIds = evidenceIds == null ? List.of() : List.copyOf(evidenceIds);
    }

    public ChatToolCallEnd(String status, String errorCode, String dataVersion, List<String> evidenceIds,
            Boolean truncated, Boolean nextAllowed) {
        this(status, errorCode, dataVersion, evidenceIds, truncated, nextAllowed, null);
    }

    public static ChatToolCallEnd failed(String errorCode) {
        return new ChatToolCallEnd("failed", errorCode, null, List.of(), null, null);
    }
}
