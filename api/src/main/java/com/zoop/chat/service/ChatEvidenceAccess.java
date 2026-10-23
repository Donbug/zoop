package com.zoop.chat.service;

import com.zoop.document.evidence.service.EvidenceService.Readability;
import java.time.Instant;

/** Whether a cited evidence id is readable right now, at the job's pinned graph version and as-of. */
@FunctionalInterface
public interface ChatEvidenceAccess {
    boolean readable(String evidenceId, String graphVersion, Instant asOf, String requestId);

    /**
     * The same judgement, keeping a denial apart from a state that could not be checked. Without its own answer an access
     * can only deny.
     */
    default Readability readability(String evidenceId, String graphVersion, Instant asOf, String requestId) {
        return readable(evidenceId, graphVersion, asOf, requestId) ? Readability.READABLE : Readability.DENIED;
    }
}
