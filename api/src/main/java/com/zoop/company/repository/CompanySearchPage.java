package com.zoop.company.repository;

import java.time.Instant;
import java.util.List;

/** asOfRequested: the caller (or the first page it continues) asked for that time; otherwise asOf only records the read. */
public record CompanySearchPage(List<CompanySearchRow> items, String nextCursor,
                                String graphVersion, Instant asOf, boolean asOfRequested) {
    public CompanySearchPage {
        items = List.copyOf(items);
    }
}
