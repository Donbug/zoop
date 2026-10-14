package com.zoop.company.repository;

import java.time.Instant;
import java.util.List;

public record CompanySearchPage(List<CompanySearchRow> items, String nextCursor,
                                String graphVersion, Instant asOf) {
    public CompanySearchPage {
        items = List.copyOf(items);
    }
}
