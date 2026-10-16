package com.zoop.company.graph;

import java.time.Instant;
import java.util.List;

/**
 * Query boundary for version-pinned per-company issue counts owned by GraphDB. asOf filters the version only when
 * asOfRequested; otherwise it is the read time already pinned by an earlier page and is echoed back unchanged.
 */
public interface CompanyIssueCountQuery {
    CompanyIssueCountSnapshot countIssues(List<String> companyIds, String graphVersion, Instant asOf, boolean asOfRequested);
}
