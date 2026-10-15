package com.zoop.document.evidence.dto;

import java.time.Instant;

/** OpenAPI {@code EvidenceArticle}: all four keys are always present. {@code publishedAt} is set only for a datetime precision. */
public record EvidenceArticle(String title, String publisher, String url, Instant publishedAt) {
}
