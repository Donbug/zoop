package com.zoop.company.graph;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/** Query boundary for version-pinned per-company issue counts owned by GraphDB. */
public interface CompanyIssueCountQuery {
    Map<String, Long> countIssues(List<String> companyIds, String graphVersion, Instant asOf);
}
