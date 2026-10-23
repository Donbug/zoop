package com.zoop.chat.service;

import com.zoop.document.evidence.service.EvidenceService;
import java.time.Instant;
import org.springframework.stereotype.Component;

/**
 * {@link ChatEvidenceAccess} through the public evidence read: the same document state, rights registry, pinned graph
 * visibility and import-receipt membership as {@code GET /api/v1/evidence/{id}}. It opens its own read transaction, so it is
 * never called inside a chat write transaction.
 */
@Component
public class EvidenceReadAccess implements ChatEvidenceAccess {
    private final EvidenceService evidence;

    public EvidenceReadAccess(EvidenceService evidence) {
        this.evidence = evidence;
    }

    @Override
    public boolean readable(String evidenceId, String graphVersion, Instant asOf, String requestId) {
        return evidence.readable(evidenceId, graphVersion, asOf, requestId);
    }

    @Override
    public EvidenceService.Readability readability(String evidenceId, String graphVersion, Instant asOf,
            String requestId) {
        return evidence.readability(evidenceId, graphVersion, asOf, requestId);
    }
}
