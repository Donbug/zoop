package com.zoop.chat.service;

import java.time.Instant;
import java.util.Optional;
import java.util.Set;

/** Which company and issue ids are visible right now in a job's pinned graph at its asOf, with the current exclusions. */
@FunctionalInterface
public interface ChatTargetAccess {
    /** The visible ones among {@code ids}, or empty when that could not be checked: then none may be shown. */
    Optional<Set<String>> visible(Set<String> ids, String graphVersion, Instant asOf, String requestId);
}
