package com.zoop.chat.tool;

import java.util.HashSet;
import java.util.List;

/**
 * One planned tool call in the common request envelope (design summary 5.1): the capability, its targets and a result limit.
 * The job, graph version and asOf are never part of it: the runner takes them from the run's frozen context
 * ({@link ChatToolScope}), and a member id is never accepted from a plan.
 */
public record ChatToolRequest(String capabilityId, List<String> targets, int limit) {
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
    }
}
