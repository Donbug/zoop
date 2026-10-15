package com.zoop.document.importer;

import java.util.List;

/** A validated batch of 1 to {@value #MAX_ITEMS} items, run in order. */
public record ImportRequest(List<ImportItem> items) {
    public static final int MAX_ITEMS = 100;
}
