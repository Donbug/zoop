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
 * rights apply. A meaningful term in the requirement narrows the authorized documents against the exact verified extracted
 * text; a generic request such as "최근 소식" keeps the newest-first document read. The first 100 documents per target are a
 * hard scan bound and an unread next page is reported as truncation, never as no match.
 *
 * <p>Each quote of a document is one {@code evidence} item labelled with the document's title, as {@code evidence.resolve}
 * reports evidence: a title may reach a model only with a quote its source's grant allows, and a document with no quote to
 * pass on is left out. A company the catalog does not know is absent. More documents or quotes than the limit mark the result
 * truncated, so what was left out is never taken for none. A read that cannot be made is {@link ChatToolUnavailable}.
 */
@Component
public class DocumentSearchTool implements ChatTool {
    private static final int MAX_SCAN_DOCUMENTS = 100;

    /** The public read of one company's documents, newest first, at most {@code limit}. */
    @FunctionalInterface
    public interface Documents {
        Response list(String companyId, String from, String graphVersion, String asOf, int limit, String requestId);
    }

    @FunctionalInterface
    interface TextSearch {
        boolean matches(String articleId, String version, String title, String query);
    }

    private final Documents documents;
    private final TextSearch textSearch;

    @Autowired
    public DocumentSearchTool(CompanyDocumentsService service, DocumentTextSearch textSearch) {
        this((company, from, version, asOf, limit, trace) -> service.list(company, null, from, null, null, version, asOf, null,
                limit, trace), textSearch::matches);
    }

    public DocumentSearchTool(Documents documents) {
        this(documents, (article, version, title, query) -> true);
    }

    DocumentSearchTool(Documents documents, TextSearch textSearch) {
        this.documents = documents;
        this.textSearch = textSearch;
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
        boolean filtered = !DocumentTextSearch.terms(request.searchText()).isEmpty();
        int scanLimit = filtered ? Math.min(MAX_SCAN_DOCUMENTS, Math.max(request.limit() * 5, request.limit()))
                : request.limit();
        Set<String> passed = new LinkedHashSet<>();
        List<ChatToolItem> items = new ArrayList<>();
        boolean truncated = false;
        for (String company : request.targets()) {
            Response page;
            try {
                page = documents.list(company, from, scope.graphVersionId(), asOf, scanLimit, scope.traceId());
            } catch (CustomException failed) {
                if (failed.getErrorCode() == ErrorCode.RESOURCE_NOT_FOUND) continue;
                throw new ChatToolUnavailable("the documents of " + company + " cannot be read", failed);
            } catch (DataAccessException | TransactionException failed) {
                throw new ChatToolUnavailable("the documents of " + company + " cannot be read", failed);
            }
            if (page.nextCursor() != null) truncated = true;
            for (var document : page.items()) {
                if (filtered && !textSearch.matches(document.id(), document.documentVersion(), document.title(),
                        request.searchText())) continue;
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
