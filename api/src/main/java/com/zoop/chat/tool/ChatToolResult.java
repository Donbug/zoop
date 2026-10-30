package com.zoop.chat.tool;

import com.zoop.chat.executor.ChatRun;
import java.util.List;

/**
 * The common result envelope of one call (design summary 5.1). A call that did not succeed has an {@code error} code
 * ({@link ChatToolRunner#TIMEOUT}, {@link ChatToolRunner#UNAVAILABLE} or {@link ChatToolRunner#FAILED}), no items and null
 * flags: it is never an empty result, so "nothing found" is only ever reported by a call that succeeded.
 * Web hits remain separate from article evidence; provenance binds both kinds of successful read to their run.
 */
public record ChatToolResult(String schemaVersion, String toolCallId, String capabilityId, String dataVersion,
        List<ChatToolItem> items, List<String> evidenceIds, Boolean truncated, Boolean nextAllowed, String error,
        List<ChatToolPath> paths, List<ChatWebResult> webResults, Provenance provenance,
        List<ChatSelectionRecord> selectionRecords) {
    public ChatToolResult {
        items = List.copyOf(items);
        evidenceIds = List.copyOf(evidenceIds);
        paths = List.copyOf(paths);
        webResults = List.copyOf(webResults);
        selectionRecords = List.copyOf(selectionRecords);
    }

    /** A result with no selection records: every read but {@code selectionRule.read}. */
    public ChatToolResult(String schemaVersion, String toolCallId, String capabilityId, String dataVersion,
            List<ChatToolItem> items, List<String> evidenceIds, Boolean truncated, Boolean nextAllowed, String error,
            List<ChatToolPath> paths, List<ChatWebResult> webResults, Provenance provenance) {
        this(schemaVersion, toolCallId, capabilityId, dataVersion, items, evidenceIds, truncated, nextAllowed, error,
                paths, webResults, provenance, List.of());
    }

    public ChatToolResult(String schemaVersion, String toolCallId, String capabilityId, String dataVersion,
            List<ChatToolItem> items, List<String> evidenceIds, Boolean truncated, Boolean nextAllowed, String error,
            List<ChatToolPath> paths) {
        this(schemaVersion, toolCallId, capabilityId, dataVersion, items, evidenceIds, truncated, nextAllowed, error,
                paths, List.of(), null);
    }

    public ChatToolResult(String schemaVersion, String toolCallId, String capabilityId, String dataVersion,
            List<ChatToolItem> items, List<String> evidenceIds, Boolean truncated, Boolean nextAllowed, String error) {
        this(schemaVersion, toolCallId, capabilityId, dataVersion, items, evidenceIds, truncated, nextAllowed, error,
                List.of());
    }

    /**
     * Minted only by the runner after a read or a bound ledger result is validated. It never travels to a model.
     */
    public static final class Provenance {
        private final ChatRun run;
        private final ChatToolRequest request;

        private Provenance(ChatRun run, ChatToolRequest request) {
            this.run = run;
            this.request = request;
        }

        public boolean belongsTo(ChatRun candidate) {
            return run == candidate;
        }

        public ChatToolRequest request() {
            return request;
        }
    }

    static ChatToolResult succeeded(String toolCallId, ChatRun run, ChatToolRequest request, ChatToolOutput output) {
        return new ChatToolResult(ChatToolRegistry.SCHEMA_VERSION, toolCallId, request.capabilityId(), output.dataVersion(),
                output.items(), output.evidenceIds(), output.truncated(), output.nextAllowed(), null, output.paths(),
                output.webResults(), new Provenance(run, request), output.selectionRecords());
    }

    static ChatToolResult failed(String toolCallId, String capabilityId, String error) {
        return new ChatToolResult(ChatToolRegistry.SCHEMA_VERSION, toolCallId, capabilityId, null, List.of(), List.of(),
                null, null, error, List.of(), List.of(), null);
    }

    public boolean succeeded() {
        return error == null;
    }
}
