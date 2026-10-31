package com.zoop.chat.tool;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.CompanyDocumentsService;
import com.zoop.graph.read.CompanyDocumentsService.Response;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@code document.search} (Q03): the news and disclosures of the target companies, newest first, through the public company
 * documents read ({@code GET /api/v1/companies/{id}/documents}), so the same pinned version, exclusions and current source
 * rights apply. There is no text search behind it: it reads a company's documents, from {@code since} when the question gave a
 * period.
 *
 * <p>Each quote of a document is one {@code evidence} item labelled with the document's title, as {@code evidence.resolve}
 * reports evidence: a title may reach a model only with a quote its source's grant allows, and a document with no quote to
 * pass on is left out. A company the catalog does not know is absent. More documents or quotes than the limit mark the result
 * truncated, so what was left out is never taken for none. A read that cannot be made is {@link ChatToolUnavailable}.
 */
@Component
public class DocumentSearchTool implements ChatTool {
    /** The public read of one company's documents, newest first, at most {@code limit}. */
    @FunctionalInterface
    public interface Documents {
        Response list(String companyId, String from, String graphVersion, String asOf, int limit, String requestId);
    }

    private final Documents documents;

    @Autowired
    public DocumentSearchTool(CompanyDocumentsService service) {
        this((company, from, version, asOf, limit, trace) -> service.list(company, null, from, null, null, version, asOf, null,
                limit, trace));
    }

    public DocumentSearchTool(Documents documents) {
        this.documents = documents;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.DOCUMENT_SEARCH;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        if (scope.graphVersionId() == null) throw new ChatToolUnavailable("the question froze no graph version");
        String from = request.since() == null ? null : request.since().toString();
        String asOf = scope.asOf() == null ? null : scope.asOf().toString();
        Set<String> passed = new LinkedHashSet<>();
        List<ChatToolItem> items = new ArrayList<>();
        boolean truncated = false;
        for (String company : request.targets()) {
            Response page;
            try {
                page = documents.list(company, from, scope.graphVersionId(), asOf, request.limit(), scope.traceId());
            } catch (CustomException failed) {
                if (failed.getErrorCode() == ErrorCode.RESOURCE_NOT_FOUND) continue;
                throw new ChatToolUnavailable("the documents of " + company + " cannot be read", failed);
            } catch (DataAccessException | TransactionException failed) {
                throw new ChatToolUnavailable("the documents of " + company + " cannot be read", failed);
            }
            if (page.nextCursor() != null) truncated = true;
            for (var document : page.items()) {
                for (var quote : document.quotes()) {
                    // The runner interrupts a read that ran out of time: stop instead of reading on.
                    if (Thread.currentThread().isInterrupted()) throw new ChatToolUnavailable("read interrupted");
                    String id = quote.evidenceId();
                    if (passed.contains(id) || (request.evidenceScope() != null && !request.evidenceScope().contains(id))) continue;
                    if (passed.size() >= request.limit()) {
                        truncated = true;
                        continue;
                    }
                    passed.add(id);
                    items.add(new ChatToolItem(id, "evidence", label(document.title(), document.publishedAt()), List.of(company),
                            List.of(id)));
                }
            }
        }
        return new ChatToolOutput(scope.graphVersionId(), items, List.copyOf(passed), truncated, false);
    }

    private static String label(String title, Instant publishedAt) {
        return publishedAt == null ? title : title + " (" + publishedAt + ")";
    }
}
