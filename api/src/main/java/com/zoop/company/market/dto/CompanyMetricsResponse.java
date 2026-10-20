package com.zoop.company.market.dto;

import java.time.Instant;
import java.util.List;

public record CompanyMetricsResponse(String status, String companyId, CompanyQuoteResponse.Source source,
        Instant asOf, List<Metric> items, String reasonCode, String reason) {
    public static CompanyMetricsResponse unavailable(String id, String code, String reason) {
        return new CompanyMetricsResponse("unavailable", id, null, null, List.of(), code, reason);
    }
    public static CompanyMetricsResponse available(String id, CompanyQuoteResponse.Source source, Instant asOf,
            List<Metric> items) {
        return new CompanyMetricsResponse("available", id, source, asOf, List.copyOf(items), null, null);
    }
    public record Metric(String code, String label, String value, String basis) { }
}
