package com.zoop.chat.tool;

import java.time.Instant;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * One planned tool call in the common request envelope (design summary 5.1): the capability, its targets and a result limit.
 * {@code evidenceScope}, when not null, is the only evidence the call may pass on (the member narrowed the selection to it).
 * {@code since}, when not null, is the moment a comparison read compares the run's pinned graph with (Q05: the public graph
 * of that moment), or where a document read starts; null for every other read, and for a comparison with the previous public graph.
 * {@code searchText} is the server-owned requirement text used only by {@code document.search}. It is part of the canonical
 * request so two differently worded searches never share a cached result.
 * The job, graph version and asOf are never part of it: the runner takes them from the run's frozen context
 * ({@link ChatToolScope}), and a member id is never accepted from a plan.
 */
public record ChatToolRequest(String capabilityId, List<String> targets, int limit, List<String> evidenceScope,
        Instant since, String searchText) {
    /** Targets one call may take: the fan-out limit of a dependent stage. */
    public static final int MAX_TARGETS = 5;
    /** Documents (evidence) one answer reads at most. */
    public static final int MAX_LIMIT = 20;

    public ChatToolRequest {
        if (capabilityId == null || capabilityId.isBlank()) throw new IllegalArgumentException("a tool call needs a capability");
        if (targets == null || targets.isEmpty() || targets.size() > MAX_TARGETS) {
            throw new IllegalArgumentException("a tool call takes 1 to " + MAX_TARGETS + " targets");
        }
        targets = List.copyOf(targets);
        if (targets.stream().anyMatch(String::isBlank) || new HashSet<>(targets).size() != targets.size()) {
            throw new IllegalArgumentException("tool call targets must be distinct ids");
        }
        if (limit < 1 || limit > MAX_LIMIT) throw new IllegalArgumentException("a tool call limit is 1 to " + MAX_LIMIT);
        evidenceScope = evidenceScope == null ? null : List.copyOf(new LinkedHashSet<>(evidenceScope));
        searchText = searchText == null || searchText.isBlank() ? null : searchText.strip();
        if (searchText != null && searchText.codePointCount(0, searchText.length()) > 500) {
            throw new IllegalArgumentException("document search text is at most 500 characters");
        }
        if (searchText != null && !ChatCapability.DOCUMENT_SEARCH.id().equals(capabilityId)) {
            throw new IllegalArgumentException("search text belongs only to document.search");
        }
    }

    public ChatToolRequest(String capabilityId, List<String> targets, int limit, List<String> evidenceScope,
            Instant since) {
        this(capabilityId, targets, limit, evidenceScope, since, null);
    }

    public ChatToolRequest(String capabilityId, List<String> targets, int limit, List<String> evidenceScope) {
        this(capabilityId, targets, limit, evidenceScope, null, null);
    }

    /** A call that may pass on any evidence it reads. */
    public ChatToolRequest(String capabilityId, List<String> targets, int limit) {
        this(capabilityId, targets, limit, null, null, null);
    }
}
