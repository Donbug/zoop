package com.zoop.company.graph;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Objects;

/** Public, immutable graph data needed by getCompany after snapshot selection and disclosure filtering. */
public record CompanyGraphSnapshot(String graphVersion, Instant asOf, boolean companyFound,
        List<CompanyIssueRef> directIssues, List<CompanyIssueRef> structuralIssues, Summary summary) {
    public CompanyGraphSnapshot {
        Objects.requireNonNull(graphVersion, "graphVersion");
        Objects.requireNonNull(asOf, "asOf");
        directIssues = List.copyOf(directIssues);
        structuralIssues = List.copyOf(structuralIssues);
    }

    public record CompanyIssueRef(String title, String issueId, LocalDate eventTime, String timePrecision,
            String role, String assertionStatus, long evidenceCount, List<BasisOut> basis) {
        public CompanyIssueRef { basis = List.copyOf(basis); }
    }

    public record BasisOut(String edgeId, String relationType, String sourceUrl, Instant verifiedAt,
            LocalDate validFrom, LocalDate validUntil, List<String> countries) {
        public BasisOut { countries = List.copyOf(countries); }
    }

    public record Summary(String text, List<String> evidenceIds, Instant generatedAt, String resultVersion) {
        public Summary { evidenceIds = List.copyOf(evidenceIds); }
    }
}
