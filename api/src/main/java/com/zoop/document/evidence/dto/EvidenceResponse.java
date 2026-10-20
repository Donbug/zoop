package com.zoop.document.evidence.dto;

import java.util.List;

import com.zoop.common.response.Metadata;
import tools.jackson.databind.JsonNode;

/**
 * OpenAPI {@code EvidenceResponse}. Every key is always serialized (absent values as {@code null}). {@code start} and
 * {@code end} are Unicode code point offsets, {@code end} exclusive, never UTF-16 indexes. {@code sentiment} and
 * {@code analysisStatus} are not produced by this read and are always {@code null}; {@code documentSummary} is the stored
 * summary result of the latest request, validated, or {@code null}.
 */
public record EvidenceResponse(String id, String quote, long start, long end, String articleId, String articleVersion,
        EvidenceArticle article, Boolean quoteVerified, List<String> eventIds, Metadata metadata, Object sentiment,
        String documentVersion, JsonNode documentSummary, Object analysisStatus, JsonNode analysisProvenance,
        String resultVersion) {
}
