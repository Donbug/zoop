package com.zoop.chat.tool;

import java.util.List;

/**
 * The common result envelope of one call (design summary 5.1). A call that did not succeed has an {@code error} code
 * ({@link ChatToolRunner#TIMEOUT}, {@link ChatToolRunner#UNAVAILABLE} or {@link ChatToolRunner#FAILED}), no items and null
 * flags: it is never an empty result, so "nothing found" is only ever reported by a call that succeeded.
 */
public record ChatToolResult(String schemaVersion, String toolCallId, String capabilityId, String dataVersion,
        List<ChatToolItem> items, List<String> evidenceIds, Boolean truncated, Boolean nextAllowed, String error,
        List<ChatToolPath> paths) {
    public ChatToolResult {
        items = List.copyOf(items);
        evidenceIds = List.copyOf(evidenceIds);
        paths = List.copyOf(paths);
    }

    public ChatToolResult(String schemaVersion, String toolCallId, String capabilityId, String dataVersion,
            List<ChatToolItem> items, List<String> evidenceIds, Boolean truncated, Boolean nextAllowed, String error) {
        this(schemaVersion, toolCallId, capabilityId, dataVersion, items, evidenceIds, truncated, nextAllowed, error,
                List.of());
    }

    static ChatToolResult succeeded(String toolCallId, String capabilityId, ChatToolOutput output) {
        return new ChatToolResult(ChatToolRegistry.SCHEMA_VERSION, toolCallId, capabilityId, output.dataVersion(),
                output.items(), output.evidenceIds(), output.truncated(), output.nextAllowed(), null, output.paths());
    }

    static ChatToolResult failed(String toolCallId, String capabilityId, String error) {
        return new ChatToolResult(ChatToolRegistry.SCHEMA_VERSION, toolCallId, capabilityId, null, List.of(), List.of(),
                null, null, error);
    }

    public boolean succeeded() {
        return error == null;
    }
}
