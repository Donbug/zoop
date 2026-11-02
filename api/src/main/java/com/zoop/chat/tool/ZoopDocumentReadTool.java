package com.zoop.chat.tool;

import com.zoop.chat.service.ChatZoopDocs;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;

/** Common fixed-document read for approved ZOOP policies, help and screen guides. */
abstract class ZoopDocumentReadTool implements ChatTool, InitializingBean {
    /** Must stay within the quote contract enforced by ChatModelStages. */
    private static final int MAX_QUOTE_LENGTH = 2_000;
    private final ChatZoopDocs docs;
    private final ChatCapability capability;
    private final boolean requireReadyAtStartup;

    ZoopDocumentReadTool(ChatZoopDocs docs, ChatCapability capability, boolean requireReadyAtStartup) {
        this.docs = docs;
        this.capability = capability;
        this.requireReadyAtStartup = requireReadyAtStartup;
    }

    @Override
    public final ChatCapability capability() {
        return capability;
    }

    /** An enabled help binding is an operator assertion that every fixed document is approved and in effect. */
    @Override
    public final void afterPropertiesSet() {
        if (!requireReadyAtStartup) return;
        try {
            for (String docId : capability.documents()) {
                var document = docs.inEffect(docId, null);
                if (document.isEmpty()) {
                    throw new IllegalStateException("Approved chat document is not in effect: " + docId);
                }
                String invalid = invalid(document.get());
                if (invalid != null) throw new IllegalStateException(invalid + ": " + docId);
            }
        } catch (DataAccessException | TransactionException unavailable) {
            throw new IllegalStateException("Approved chat documents cannot be checked", unavailable);
        }
    }

    @Override
    public final ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        Set<String> allowed = Set.copyOf(capability.documents());
        Set<String> passed = new LinkedHashSet<>();
        List<String> versions = new ArrayList<>();
        boolean truncated = false;
        List<ChatToolItem> items = new ArrayList<>();
        for (String id : request.targets()) {
            if (!allowed.contains(id)) continue;
            if (Thread.currentThread().isInterrupted()) throw new ChatToolUnavailable("read interrupted");
            Optional<ChatZoopDocs.Document> document;
            try {
                document = docs.inEffect(id, scope.asOf());
            } catch (DataAccessException | TransactionException unavailable) {
                throw new ChatToolUnavailable("the ZOOP documents cannot be read", unavailable);
            }
            if (document.isEmpty()) continue;
            var d = document.get();
            String invalid = invalid(d);
            if (invalid != null) throw new ChatToolUnavailable("the approved ZOOP document is invalid: " + id);
            List<String> evidence = new ArrayList<>();
            for (var quote : d.quotes()) {
                if (request.evidenceScope() != null && !request.evidenceScope().contains(quote.evidenceId())) continue;
                if (passed.size() >= request.limit()) {
                    truncated = true;
                } else if (passed.add(quote.evidenceId())) {
                    evidence.add(quote.evidenceId());
                }
            }
            versions.add(d.docId() + "@" + d.version());
            items.add(new ChatToolItem(d.docId(), "zoop_doc", d.title(), List.of(), evidence));
        }
        return new ChatToolOutput("zoop-docs/" + String.join(",", versions), items, List.copyOf(passed), truncated, false);
    }

    /** Rechecked on every read because a later approved version can become effective without restarting this instance. */
    private static String invalid(ChatZoopDocs.Document document) {
        if (document.quotes().isEmpty()) return "Approved chat document has no sections";
        if (document.quotes().size() > ChatToolRequest.MAX_LIMIT) return "Approved chat document has too many sections";
        if (document.quotes().stream().anyMatch(quote -> quote.text().length() > MAX_QUOTE_LENGTH)) {
            return "Approved chat document has an oversized section";
        }
        return null;
    }
}
