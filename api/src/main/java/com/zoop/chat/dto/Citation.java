package com.zoop.chat.dto;

import java.time.Instant;

/**
 * OpenAPI {@code Citation}: a quote of a pinned article version ({@code article}), an approved ZOOP document
 * ({@code zoop_doc}) or a company's catalog profile ({@code company_profile}, {@code docId} is the company id).
 */
public record Citation(String sourceKind, String evidenceId, String quote, String articleId, String articleVersion,
        String docId, String docVersion, int start, int end, String articleTitle, String publisher, Instant publishedAt,
        String url) {
}
