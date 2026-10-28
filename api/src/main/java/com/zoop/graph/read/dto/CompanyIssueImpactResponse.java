package com.zoop.graph.read.dto;

import com.zoop.common.response.Metadata;
import java.util.List;

/** OpenAPI {@code ImpactPath}: the visible path between one issue and one company. */
public record CompanyIssueImpactResponse(String companyId, String issueId, String pathStatus, String pathType,
        String edgeId, List<Step> steps, BusinessPath businessPath, Impact impact, Metadata metadata) {

    public record Step(String id, String kind, String reason, List<String> evidenceIds) { }

    public record BusinessPath(String status, String reason, List<String> companyIds, List<BusinessLink> links) { }

    public record BusinessLink(String supplierCompanyId, String customerCompanyId, String reason,
            List<String> evidenceIds) { }

    public record Impact(String status, String reason, List<Result> results) { }

    public record Result(String impactId, String status, String label, List<String> evidenceIds, Effects effects) { }

    public record Effects(List<String> positive, List<String> negative, List<String> neutral, List<String> uncertain) { }
}
