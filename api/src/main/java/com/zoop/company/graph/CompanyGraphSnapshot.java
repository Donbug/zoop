package com.zoop.company.graph;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** Public, immutable graph data needed by getCompany after snapshot selection and disclosure filtering. */
public record CompanyGraphSnapshot(String graphVersion, Instant asOf, boolean companyFound,
        List<CompanyIssueRef> directIssues, List<CompanyIssueRef> structuralIssues, Summary summary, String source) {
    public CompanyGraphSnapshot(String graphVersion, Instant asOf, boolean companyFound,
            List<CompanyIssueRef> directIssues, List<CompanyIssueRef> structuralIssues, Summary summary) {
        this(graphVersion, asOf, companyFound, directIssues, structuralIssues, summary, "public_graph_snapshot");
    }
    public CompanyGraphSnapshot {
        Objects.requireNonNull(graphVersion, "graphVersion");
        Objects.requireNonNull(asOf, "asOf");
        directIssues = List.copyOf(directIssues);
        structuralIssues = List.copyOf(structuralIssues);
    }

    /** eventTime keeps the precision named by timePrecision ("2026", "2026-09", a date or an instant). */
    public record CompanyIssueRef(String title, String issueId, String eventTime, String timePrecision,
            String role, String assertionStatus, long evidenceCount, List<BasisOut> basis) {
        public CompanyIssueRef { basis = List.copyOf(basis); }
    }

    /** validity: the business relation status at the response's asOf (scheduled·active·ended·unknown, FS042). */
    public record BasisOut(String edgeId, String relationType, String sourceUrl, Instant verifiedAt,
            String validFrom, String validUntil, List<String> countries, String validity) {
        public BasisOut { countries = List.copyOf(countries); }
    }

    public record Summary(String text, List<String> evidenceIds, Instant generatedAt, String resultVersion) {
        public Summary { evidenceIds = List.copyOf(evidenceIds); }
    }
}
