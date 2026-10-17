package com.zoop.company.dto;

import java.util.List;

public record CompanyListResponse(List<CompanySummaryResponse> items,
                                  CompanyListMetadata metadata,
                                  String nextCursor) {
    public CompanyListResponse {
        items = List.copyOf(items);
    }
}
