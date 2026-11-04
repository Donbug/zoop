package com.zoop.graph.read.dto;

import com.zoop.common.response.Metadata;
import java.util.List;

/** Verified S3 quote effects for one direct issue-company relation in a pinned graph. */
public record CompanyIssueImpactAssessment(String companyId, String issueId, String status, String reason,
        List<Result> results, Metadata metadata) {
    public CompanyIssueImpactAssessment {
        results = List.copyOf(results);
    }

    public record Result(String impactId, String status, String label, List<String> evidenceIds,
            Effects effects, Provenance provenance) {
        public Result {
            evidenceIds = List.copyOf(evidenceIds);
        }
    }

    public record Effects(List<String> positive, List<String> negative, List<String> neutral, List<String> uncertain) { }
    public record Provenance(String sourceKind, String executionMode, String recordingKind) { }
}
