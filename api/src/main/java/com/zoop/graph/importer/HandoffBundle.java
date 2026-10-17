package com.zoop.graph.importer;

import java.util.List;
import java.util.Map;

/**
 * The parts of a fully validated {@code zoop-graph-handoff-bundle-1} that the import maps. Every field here has passed the
 * closed schema, the reference closure and the id formulas of {@link HandoffBundleVerifier}; nothing is trusted from the producer
 * that the verifier did not check. Provenance the app does not map ({@code period}, source events, decisions, source references,
 * per-basis countries) stays in the retained receipt and is never dropped silently.
 */
public record HandoffBundle(String handoffId, String manifestDigest, String sourceKind, String executionMode,
        String recordingKind, String policyVersion, Map<String, String> files, List<SourcePin> sources,
        List<Company> companies, List<Issue> issues, List<Relation> relations, List<Evidence> evidence,
        List<Article> articles) {

    public HandoffBundle {
        files = Map.copyOf(files);
        sources = List.copyOf(sources);
        companies = List.copyOf(companies);
        issues = List.copyOf(issues);
        relations = List.copyOf(relations);
        evidence = List.copyOf(evidence);
        articles = List.copyOf(articles);
    }

    /** One pinned S3 relation job with its S2 upstream, as the manifest and the bundle both list it. */
    public record SourcePin(String relationJobId, String relationInputDigest, String upstreamJobId,
            String upstreamInputDigest, String upstreamDigest, String reviewDigest) {
    }

    /** {@code id} is the public company id (it must equal {@code companies.id}). */
    public record Company(String id, String label) {
    }

    /**
     * @param title            becomes the issue label
     * @param eventTime        as the source states it; its precision is {@code timePrecision} (never widened)
     * @param assertionStatus  the producer's field; the format-1 snapshot carries it on the relations only
     * @param geography        {@code domestic} or {@code international} by an operator field verdict
     */
    public record Issue(String id, String title, String action, String target, String eventTime, String timePrecision,
            String assertionStatus, String geography, String geographyPolicyVersion, List<String> geographyEvidenceIds,
            List<String> evidenceIds) {
        public Issue {
            geographyEvidenceIds = List.copyOf(geographyEvidenceIds);
            evidenceIds = List.copyOf(evidenceIds);
        }
    }

    /** {@code origin} is the provenance origin: {@code s3-relation}, {@code manual-operator-review} or an S2 comparison. */
    public record Relation(String id, String type, String source, String target, String role, String assertionStatus,
            List<String> evidenceIds, List<Basis> basis, String origin) {
        public Relation {
            evidenceIds = List.copyOf(evidenceIds);
            basis = List.copyOf(basis);
        }
    }

    /** {@code validUntil} is the exclusive end of a validity window; null means unknown, never "forever". */
    public record Basis(String verifiedAt, String validFrom, String validUntil) {
    }

    /**
     * One evidence span. {@code sourceEvidenceId} and {@code rawLocatorIds} are the S2-1 facts the importer re-derives from
     * the current export of the document.
     */
    public record Evidence(String id, String articleId, String articleVersion, int start, int end, String quoteSha256,
            List<String> rawLocatorIds, String documentId, String documentVersion, String rawVersion,
            String textArtifactId, String sourceEvidenceId) {
        public Evidence {
            rawLocatorIds = List.copyOf(rawLocatorIds);
        }
    }

    /** {@code precision} is {@code datetime} (an instant), {@code day} (a calendar date) or {@code unknown} (null). */
    public record Article(String articleId, String articleVersion, String documentId, String documentVersion,
            String rawVersion, String title, String url, String publishedAt, String precision,
            List<ObservationPin> observations) {
        public Article {
            observations = List.copyOf(observations);
        }
    }

    /** One recorded observation of the document: the exact S2-1 selector plus the grant it was exported under. */
    public record ObservationPin(String roundId, String sourceId, int page, int ordinal, String observedAt,
            String grantId, String grantRevision) {
    }
}
