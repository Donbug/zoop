package com.zoop.graph.exclusion;

import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Outcome of one run: the change written ({@code applied}) or that nothing had to change ({@code unchanged}: every proposed
 * target was already excluded, or no target of a lift still was), or the one failure that stopped it. Counts and ids of versions
 * only, never target ids or content.
 */
public record ExclusionResult(String action, String outcome, long revision, List<VersionChange> versions,
        ExclusionException failure) {
    public static final String APPLIED = "applied";
    public static final String UNCHANGED = "unchanged";

    public ExclusionResult {
        versions = versions == null ? List.of() : List.copyOf(versions);
    }

    public static ExclusionResult failed(String action, ExclusionException failure) {
        return new ExclusionResult(action, null, 0, List.of(), failure);
    }

    public boolean succeeded() {
        return failure == null;
    }

    /**
     * One version the run looked at. {@code changed} counts the targets this run excluded or lifted, by kind; {@code unchanged}
     * the ones already in that state. {@code handoffId} is the report's handoff ({@code null} for a lift).
     */
    public record VersionChange(String graphVersionId, String handoffId, boolean exposed, Map<String, Integer> changed,
            Map<String, Integer> unchanged) {
        public VersionChange {
            changed = new TreeMap<>(changed);
            unchanged = new TreeMap<>(unchanged);
        }
    }
}
