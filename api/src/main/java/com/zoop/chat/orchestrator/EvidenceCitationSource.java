package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.service.ChatCompanyProfiles;
import com.zoop.chat.service.ChatZoopDocs;
import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import java.time.Instant;
import java.util.Optional;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@link ChatCitationSource} through {@code GET /api/v1/evidence/{id}}'s own read, at the pinned version and asOf. A company
 * profile quote is cited from the catalog as {@code company_profile}: the whole quoted text, the company id as {@code docId},
 * only while its company is visible at that version and asOf ({@link ChatCompanyProfiles#readability}). A ZOOP document
 * section is cited as {@code zoop_doc} with its document id, version and code-point span and no publisher (the public
 * contract leaves it null), only while that version is in effect at the asOf and still now ({@link ChatZoopDocs#readability}).
 */
@Component
public class EvidenceCitationSource implements ChatCitationSource {
    private final EvidenceService evidence;
    private final ChatCompanyProfiles profiles;
    private final ChatZoopDocs docs;

    public EvidenceCitationSource(EvidenceService evidence, ChatCompanyProfiles profiles, ChatZoopDocs docs) {
        this.evidence = evidence;
        this.profiles = profiles;
        this.docs = docs;
    }

    @Override
    public Optional<Citation> cite(String evidenceId, String graphVersion, Instant asOf, String traceId) {
        Optional<ChatCompanyProfiles.Quote> profile;
        try {
            profile = profiles.byId(evidenceId);
        } catch (DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("the catalog could not be read for " + evidenceId, unavailable);
        }
        if (profile.isPresent()) {
            var q = profile.get();
            switch (profiles.readability(q, graphVersion, asOf, traceId)) {
                case DENIED -> { return Optional.empty(); }
                case UNAVAILABLE -> throw new ChatToolUnavailable("the company of " + evidenceId + " could not be checked");
                case READABLE -> { }
            }
            return Optional.of(new Citation("company_profile", q.evidenceId(), q.text(), null, null, q.companyId(), null, 0,
                    q.text().codePointCount(0, q.text().length()), q.title(), ChatCompanyProfiles.PUBLISHER, null, q.url()));
        }
        Optional<ChatZoopDocs.Quote> doc;
        try {
            doc = docs.byId(evidenceId);
        } catch (DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("the ZOOP documents could not be read for " + evidenceId, unavailable);
        }
        if (doc.isPresent()) {
            var q = doc.get();
            switch (docs.readability(q, asOf)) {
                case DENIED -> { return Optional.empty(); }
                case UNAVAILABLE -> throw new ChatToolUnavailable("the version of " + evidenceId + " could not be checked");
                case READABLE -> { }
            }
            return Optional.of(new Citation("zoop_doc", q.evidenceId(), q.text(), null, null, q.docId(), q.docVersion(),
                    q.start(), q.end(), q.title(), null, null, null));
        }
        EvidenceResponse read;
        try {
            read = evidence.read(evidenceId, null, graphVersion, asOf == null ? null : asOf.toString(), null, traceId);
        } catch (CustomException refused) {
            return switch (refused.getErrorCode()) {
                case RESOURCE_NOT_FOUND, EVIDENCE_UNAVAILABLE, INVALID_REQUEST -> Optional.empty();
                default -> throw new ChatToolUnavailable("evidence " + evidenceId + " could not be read", refused);
            };
        }
        var article = read.article();
        return Optional.of(new Citation("article", read.id(), read.quote(), read.articleId(), read.articleVersion(), null,
                null, Math.toIntExact(read.start()), Math.toIntExact(read.end()), article == null ? null : article.title(),
                article == null ? null : article.publisher(), article == null ? null : article.publishedAt(),
                article == null ? null : article.url()));
    }
}
