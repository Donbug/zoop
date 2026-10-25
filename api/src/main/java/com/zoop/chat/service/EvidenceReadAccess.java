package com.zoop.chat.service;

import com.zoop.document.evidence.service.EvidenceService;
import java.time.Instant;
import org.springframework.stereotype.Component;

/**
 * {@link ChatEvidenceAccess} through the public evidence read: the same document state, rights registry, pinned graph
 * visibility and import-receipt membership as {@code GET /api/v1/evidence/{id}}. It opens its own read transaction, so it is
 * never called inside a chat write transaction. A company profile quote ({@link ChatCompanyProfiles}) is readable while the
 * catalog still holds the text it quoted and its company is visible in the pinned graph at that asOf; a ZOOP document quote
 * ({@link ChatZoopDocs}) while its version is the one in effect at that asOf. As for evidence, a state that could not be
 * checked is {@code UNAVAILABLE} and {@link #readable} treats it as not readable.
 */
@Component
public class EvidenceReadAccess implements ChatEvidenceAccess {
    private final EvidenceService evidence;
    private final ChatCompanyProfiles profiles;
    private final ChatZoopDocs docs;

    public EvidenceReadAccess(EvidenceService evidence, ChatCompanyProfiles profiles, ChatZoopDocs docs) {
        this.evidence = evidence;
        this.profiles = profiles;
        this.docs = docs;
    }

    @Override
    public boolean readable(String evidenceId, String graphVersion, Instant asOf, String requestId) {
        return readability(evidenceId, graphVersion, asOf, requestId) == EvidenceService.Readability.READABLE;
    }

    @Override
    public EvidenceService.Readability readability(String evidenceId, String graphVersion, Instant asOf,
            String requestId) {
        return profiles.check(evidenceId, graphVersion, asOf, requestId)
                .or(() -> docs.check(evidenceId, asOf))
                .orElseGet(() -> evidence.readability(evidenceId, graphVersion, asOf, requestId));
    }
}
