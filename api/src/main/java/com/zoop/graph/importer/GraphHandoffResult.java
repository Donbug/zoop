package com.zoop.graph.importer;

import java.util.Map;

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
            int evidenceRegistered, int evidenceExisting, StoredFileFact snapshot, StoredFileFact receipt) {
        public Staged {
            origins = Map.copyOf(origins);
            approvalBases = Map.copyOf(approvalBases);
        }
    }
}
