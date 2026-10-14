package com.zoop.company.graph;

import java.time.Instant;
import java.util.List;

/** Query boundary for version-pinned per-company issue counts owned by GraphDB. */
public interface CompanyIssueCountQuery {
    CompanyIssueCountSnapshot countIssues(List<String> companyIds, String graphVersion, Instant asOf);
}
