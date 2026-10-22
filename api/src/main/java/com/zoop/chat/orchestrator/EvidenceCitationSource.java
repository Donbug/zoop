package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.tool.ChatToolUnavailable;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.dto.EvidenceResponse;
import com.zoop.document.evidence.service.EvidenceService;
import java.time.Instant;
import java.util.Optional;
import org.springframework.stereotype.Component;

/** {@link ChatCitationSource} through {@code GET /api/v1/evidence/{id}}'s own read, at the pinned version and asOf. */
@Component
public class EvidenceCitationSource implements ChatCitationSource {
    private final EvidenceService evidence;

    public EvidenceCitationSource(EvidenceService evidence) {
        this.evidence = evidence;
    }

    @Override
    public Optional<Citation> cite(String evidenceId, String graphVersion, Instant asOf, String traceId) {
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
