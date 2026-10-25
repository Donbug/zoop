package com.zoop.graph.exclusion;

import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;

/**
 * Outcome of one run: the change written ({@code applied}) or that nothing had to change ({@code unchanged}: every proposed
 * target was already excluded, or no target of a lift still was), or the one failure that stopped it. Counts and ids of versions
 * only, never target ids or content. A re-run of a recorded request carries the stored result document ({@code recorded}) instead
 * of versions: it changed nothing this time.
 */
public record ExclusionResult(String action, String outcome, long revision, List<VersionChange> versions,
        ExclusionException failure, byte[] recorded) {
    public static final String APPLIED = "applied";
    public static final String UNCHANGED = "unchanged";

    public ExclusionResult {
        versions = versions == null ? List.of() : List.copyOf(versions);
    }

    public ExclusionResult(String action, String outcome, long revision, List<VersionChange> versions) {
        this(action, outcome, revision, versions, null, null);
    }

    public static ExclusionResult failed(String action, ExclusionException failure) {
        return new ExclusionResult(action, null, 0, List.of(), failure, null);
    }

    /** The result the first run of this request stored, as it stored it. */
    static ExclusionResult replayed(String action, byte[] stored) {
        Obj result = StrictJson.parseObject(stored);
        return new ExclusionResult(action, result.string("outcome"), result.node().get("revision").longValue(), List.of(), null,
                stored);
    }

    public boolean succeeded() {
        return failure == null;
    }

    public boolean replay() {
        return recorded != null;
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
