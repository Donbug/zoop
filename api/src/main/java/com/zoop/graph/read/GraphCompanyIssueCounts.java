package com.zoop.graph.read;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.company.graph.CompanyIssueCountQuery;
import com.zoop.company.graph.CompanyIssueCountSnapshot;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * searchCompanies issue counts from the same pinned, filtered snapshot as getGraph: the number of distinct public
 * issues linked to the company (INVOLVES or STRUCTURALLY_RELATED_TO), the same count as its graph node.
 */
@Component
public class GraphCompanyIssueCounts implements CompanyIssueCountQuery {
    private final PublicGraphReader reader;

    public GraphCompanyIssueCounts(PublicGraphReader reader) {
        this.reader = reader;
    }

    @Override
    public CompanyIssueCountSnapshot countIssues(List<String> companyIds, String graphVersion, Instant asOf,
            boolean asOfRequested) {
        PublicGraphReader.Pinned pinned;
        try {
            pinned = reader.read(null, graphVersion, asOfRequested ? asOf : null);
        } catch (CustomException exception) {
            // searchCompanies has no 409: without a public version the counts are simply unavailable.
            if (exception.getErrorCode() == ErrorCode.VERSION_UNAVAILABLE) {
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
            }
            throw exception;
        }
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String id : companyIds) {
            counts.put(id, (long) pinned.graph().companyIssues.getOrDefault(id, Set.of()).size());
        }
        Instant readAt = asOf != null ? asOf : pinned.selected().asOf();
        return new CompanyIssueCountSnapshot(pinned.selected().version().id(), readAt, counts);
    }
}
