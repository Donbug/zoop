package com.zoop.chat.tool;

import com.zoop.chat.service.ChatZoopDocs;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@code zoopPolicy.read}: the approved ZOOP policies in effect at the run's asOf (now without one) and still in effect now
 * ({@link ChatZoopDocs#inEffect}), each as an item with its
 * sections passed on as evidence in body order, kept within the request's evidence scope and capped at the request limit.
 * Its targets are always {@link ChatZoopDocs#POLICIES} ({@link ChatCapability#documents()}); a target that is not a policy
 * in effect is absent. It reads no graph. The data version names each policy version read. A registry that cannot be read
 * is {@link ChatToolUnavailable}, never an empty result.
 */
@Component
public class ZoopPolicyReadTool implements ChatTool {
    private final ChatZoopDocs docs;

    public ZoopPolicyReadTool(ChatZoopDocs docs) {
        this.docs = docs;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.ZOOP_POLICY_READ;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        Set<String> passed = new LinkedHashSet<>();
        List<String> versions = new ArrayList<>();
        boolean truncated = false;
        List<ChatToolItem> items = new ArrayList<>();
        for (String id : request.targets()) {
            if (Thread.currentThread().isInterrupted()) throw new ChatToolUnavailable("read interrupted");
            Optional<ChatZoopDocs.Document> document;
            try {
                document = docs.inEffect(id, scope.asOf());
            } catch (DataAccessException | TransactionException unavailable) {
                throw new ChatToolUnavailable("the ZOOP policies cannot be read", unavailable);
            }
            if (document.isEmpty()) continue;
            var d = document.get();
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
}
