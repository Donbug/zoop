package com.zoop.graph.importer;

import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;

/**
 * Outcome of one operator run: either the staged (or already staged) version or the one failure that stopped it. A failed run has
 * written nothing that outlives it: the database work is one transaction and a file the run created is removed again when that
 * transaction is known to have rolled back.
 */
public record GraphHandoffResult(Staged staged, GraphHandoffException failure) {

    public static GraphHandoffResult succeeded(Staged staged) {
        return new GraphHandoffResult(staged, null);
    }

    public static GraphHandoffResult failed(GraphHandoffException failure) {
        return new GraphHandoffResult(null, failure);
    }

    public boolean succeeded() {
        return failure == null;
    }

    /** Whether the version was newly registered or an identical import had registered it before. */
    public enum Outcome {
        STAGED("staged"), UNCHANGED("unchanged");

        private final String wire;

        Outcome(String wire) {
            this.wire = wire;
        }

        public String wire() {
            return wire;
        }
    }

    /** One artifact file of the import; {@code file} is {@code created} or {@code existing} (an identical orphan or earlier file). */
    public record StoredFileFact(String artifactId, String sha256, long bytes, String file) {
    }

    /**
     * @param origins        provenance origins of the staged relations (for example {@code manual-operator-review}), by count: the
     *                       result states explicitly how much of the staged graph is a manual operator assertion
     * @param approvalBases  by count, how the S3 relations the staged edges rest on became eligible: {@code automatic-verifier}
     *                       or {@code operator-final-approval} (a human's approval of a HOLD, not a verifier verdict)
     */
    public record Staged(String handoffId, String versionId, Outcome outcome, String manifestDigest, String bundleDigest,
            String contentDigest, String sourceKind, String executionMode, String recordingKind, Map<String, Integer> origins,
            Map<String, Integer> approvalBases, int companies, int issues, int relations, int articles, int evidence,
            int evidenceRegistered, int evidenceExisting, StoredFileFact snapshot, StoredFileFact receipt, RuleFacts rules) {
        public Staged {
            origins = Map.copyOf(origins);
            approvalBases = Map.copyOf(approvalBases);
            Objects.requireNonNull(rules);
        }
    }

    /**
     * What the publication rules did to the stored version, beside the bundle's own {@code counts}: the two revisions and the rules
     * the version fixed, what its snapshot holds, how many issues and relations they hid (the cascade included) and, per rule,
     * what its own condition matched. Counts only, never ids or content. For an {@code unchanged} import these are the version's
     * own facts (its staging rules, re-applied), never the rules enabled now; {@code ruleRevision} is {@code null} only for a
     * version staged before rules existed.
     */
    public record RuleFacts(Long ruleRevision, long reviewRevision, List<String> applied, int storedIssues, int storedRelations,
            int storedArticles, int storedEvidence, int hiddenIssues, int hiddenRelations, Map<String, RuleHits> byRule) {
        public RuleFacts {
            applied = List.copyOf(applied);
            byRule = Collections.unmodifiableMap(new TreeMap<>(byRule));
        }
    }

    /** One rule's own matches (before the cascade), as counts. */
    public record RuleHits(int issues, int relations) {
    }
}
