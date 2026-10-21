package com.zoop.chat.dto;

import java.time.Instant;

/** OpenAPI {@code Citation}: a quote of a pinned article version ({@code article}) or an approved ZOOP document ({@code zoop_doc}). */
public record Citation(String sourceKind, String evidenceId, String quote, String articleId, String articleVersion,
        String docId, String docVersion, int start, int end, String articleTitle, String publisher, Instant publishedAt,
        String url) {
}
