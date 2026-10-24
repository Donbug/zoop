package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.service.ChatCompanyProfiles;
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
 * only while its company is visible at that version and asOf ({@link ChatCompanyProfiles#readability}).
 */
@Component
public class EvidenceCitationSource implements ChatCitationSource {
    private final EvidenceService evidence;
    private final ChatCompanyProfiles profiles;

    public EvidenceCitationSource(EvidenceService evidence, ChatCompanyProfiles profiles) {
        this.evidence = evidence;
        this.profiles = profiles;
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
