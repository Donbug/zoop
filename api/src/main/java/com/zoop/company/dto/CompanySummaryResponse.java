package com.zoop.company.dto;

import java.util.List;

public record CompanySummaryResponse(
        String id,
        String name,
        String ticker,
        List<String> aliases,
        String sector,
        String brandColor,
        String logoUrl,
        long issueCount) {
    public CompanySummaryResponse {
        aliases = List.copyOf(aliases);
    }
}
