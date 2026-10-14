package com.zoop.company.repository;

import java.util.List;

public record CompanySearchPage(List<CompanySearchRow> items, String nextCursor) {
    public CompanySearchPage {
        items = List.copyOf(items);
    }
}
