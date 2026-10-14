package com.zoop.company.repository;

import java.util.List;

public record CompanySearchRow(
        String id,
        String ticker,
        String exchangeCode,
        String name,
        String market,
        List<String> aliases,
        String brandColor,
        String logoUrl,
        String sector,
        int matchRank) {
}
