package com.zoop.company.service;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import com.zoop.company.dto.CompanyListMetadata;
import com.zoop.company.dto.CompanyListResponse;
import com.zoop.company.dto.CompanySummaryResponse;
import com.zoop.company.graph.CompanyIssueCountQuery;
import com.zoop.company.graph.CompanyIssueCountSnapshot;
import com.zoop.company.repository.CompanySearchPage;
import com.zoop.company.repository.CompanySearchRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Service;

@Service
public class CompanySearchApiService {
    private static final String SOURCE = "postgresql+public_graph_snapshot";

    private final CompanySearchService searchService;
    private final CompanyIssueCountQuery issueCountQuery;

    public CompanySearchApiService(CompanySearchService searchService,
                                   CompanyIssueCountQuery issueCountQuery) {
        this.searchService = searchService;
        this.issueCountQuery = issueCountQuery;
    }

    public CompanyListResponse search(String q, String cursor, Integer limit,
                                      String graphVersion, Instant asOf, String requestId) {
        CompanySearchPage page = searchService.search(q, cursor, limit, graphVersion, asOf);
        List<String> companyIds = page.items().stream().map(CompanySearchRow::id).toList();
        CompanyIssueCountSnapshot snapshot;
        try {
            snapshot = issueCountQuery.countIssues(companyIds, page.graphVersion(), page.asOf(), page.asOfRequested());
        } catch (CustomException exception) {
            throw exception;
        } catch (RuntimeException exception) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, exception);
        }
        validateSnapshot(snapshot, companyIds);

        if (page.graphVersion() != null && !page.graphVersion().equals(snapshot.graphVersion())) {
            throw new CustomException(ErrorCode.INTERNAL_ERROR);
        }
        if (page.asOf() != null && !page.asOf().equals(snapshot.asOf())) {
            throw new CustomException(ErrorCode.INTERNAL_ERROR);
        }
        page = searchService.pinGraphSnapshot(page, snapshot.graphVersion(), snapshot.asOf(), snapshot.asOfRequested());
        Map<String, Long> counts = snapshot.counts();
        List<CompanySummaryResponse> items = page.items().stream()
                .map(company -> toSummary(company, counts.get(company.id())))
                .toList();
        CompanyListMetadata metadata = new CompanyListMetadata(
                SOURCE, snapshot.asOf(), snapshot.graphVersion(), requestId, false, List.of());
        return new CompanyListResponse(items, metadata, page.nextCursor());
    }

    private static void validateSnapshot(CompanyIssueCountSnapshot snapshot, List<String> companyIds) {
        if (snapshot == null || snapshot.graphVersion() == null || snapshot.graphVersion().isBlank()
                || snapshot.asOf() == null || snapshot.counts() == null) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        for (String companyId : companyIds) {
            Long count = snapshot.counts().get(companyId);
            if (count == null || count < 0) {
                throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
            }
        }
    }

    private static CompanySummaryResponse toSummary(CompanySearchRow company, Long issueCount) {
        if (issueCount == null || issueCount < 0) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE);
        }
        return new CompanySummaryResponse(company.id(), company.name(), company.ticker(), company.aliases(),
                company.sector(), company.brandColor(), company.logoUrl(), issueCount);
    }
}
