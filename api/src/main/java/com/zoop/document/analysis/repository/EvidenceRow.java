package com.zoop.document.analysis.repository;

import java.time.Instant;
import java.util.List;

/** The columns of {@code evidence} for a body citation of a document version: offsets are Unicode code points. */
public record EvidenceRow(String id, String articleId, String articleVersion, String textArtifactId, String quote,
        long startOffset, long endOffset, List<String> rawLocatorIds, String verificationArtifactId, Instant verifiedAt,
        Instant createdAt) {

    public EvidenceRow {
        rawLocatorIds = List.copyOf(rawLocatorIds);
    }
}
