package com.zoop.graph.snapshot;

import java.util.List;
import java.util.Objects;

/**
 * One immutable public graph version owned by the app. Fixture and imported snapshots share this model.
 * Members' holding/watch flags and the derived SHARES_ISSUE edges are never stored here; they are computed per request.
 */
public record PublicGraphSnapshot(int snapshotFormat, String versionId, String sourceBundleId, List<Company> companies,
        List<Issue> issues, List<Relation> relations, List<Article> articles, List<Evidence> evidence) {
    public static final int FORMAT = 1;

    public PublicGraphSnapshot {
        Objects.requireNonNull(versionId, "versionId");
        companies = List.copyOf(companies);
        issues = List.copyOf(issues);
        relations = List.copyOf(relations);
        articles = List.copyOf(articles);
        evidence = List.copyOf(evidence);
    }

    /** Company display values pinned to this version; the id equals {@code companies.id}. */
    public record Company(String companyId, String label, String brandColor, String logoUrl) { }

    /**
     * Canonical public issue (not a per-document mention or a per-job event candidate). Unresolved geography, or
     * geography without its supporting evidence, never reaches a snapshot. {@code eventTime} keeps the precision
     * given by {@code timePrecision} ("2026", "2026-09", "2026-09-22", an instant, or null for unknown).
     */
    public record Issue(String issueId, String label, String eventTime, String timePrecision, String action,
            String target, String geography, String geographyPolicyVersion, List<String> geographyEvidenceIds,
            List<String> articleIds, List<String> evidenceIds, String latestPublishedAt) {
        public Issue {
            geographyEvidenceIds = List.copyOf(geographyEvidenceIds);
            articleIds = List.copyOf(articleIds);
            evidenceIds = List.copyOf(evidenceIds);
        }
    }

    /** Approved source relation. Display edges group these by (relationType, source, target) at read time. */
    public record Relation(String relationId, String relationType, String source, String target, String role,
            String assertionStatus, List<String> evidenceIds, List<Basis> basis) {
        public Relation {
            evidenceIds = List.copyOf(evidenceIds);
            basis = List.copyOf(basis);
        }
    }

    public record Basis(String verifiedAt, String validFrom, String validUntil) { }

    /**
     * Article version pinned to this snapshot; publishedAt keeps the provider precision ("2026-10-01" or an instant),
     * or is null when the publication time is unknown (the article then never counts as published before an asOf).
     */
    public record Article(String articleId, String version, String title, String url, String publishedAt) { }

    public record Evidence(String evidenceId, String articleId, String articleVersion, int start, int end) { }
}
