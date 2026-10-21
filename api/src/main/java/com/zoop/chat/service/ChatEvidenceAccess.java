package com.zoop.chat.service;

import java.time.Instant;

/** Whether a cited evidence id is readable right now, at the job's pinned graph version and as-of. */
@FunctionalInterface
public interface ChatEvidenceAccess {
    boolean readable(String evidenceId, String graphVersion, Instant asOf, String requestId);
}
