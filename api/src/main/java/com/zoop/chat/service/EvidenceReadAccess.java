package com.zoop.chat.service;

import com.zoop.document.evidence.service.EvidenceService;
import java.time.Instant;
import org.springframework.stereotype.Component;

/**
 * {@link ChatEvidenceAccess} through the public evidence read: the same document state, rights registry, pinned graph
 * visibility and import-receipt membership as {@code GET /api/v1/evidence/{id}}. It opens its own read transaction, so it is
 * never called inside a chat write transaction. A company profile quote ({@link ChatCompanyProfiles}) is readable while the
 * catalog still holds the text it quoted.
 */
@Component
public class EvidenceReadAccess implements ChatEvidenceAccess {
    private final EvidenceService evidence;
    private final ChatCompanyProfiles profiles;

    public EvidenceReadAccess(EvidenceService evidence, ChatCompanyProfiles profiles) {
        this.evidence = evidence;
        this.profiles = profiles;
    }

    @Override
    public boolean readable(String evidenceId, String graphVersion, Instant asOf, String requestId) {
        return profiles.byId(evidenceId).isPresent() || evidence.readable(evidenceId, graphVersion, asOf, requestId);
    }

    @Override
    public EvidenceService.Readability readability(String evidenceId, String graphVersion, Instant asOf,
            String requestId) {
        if (profiles.byId(evidenceId).isPresent()) return EvidenceService.Readability.READABLE;
        return evidence.readability(evidenceId, graphVersion, asOf, requestId);
    }
}
