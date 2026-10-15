package com.zoop.document.analysis.service;

import java.util.List;

/** A body citation of the analysed version; the service adds the verification receipt and the time. */
public record EvidenceDraft(String id, String articleId, String articleVersion, String textArtifactId, String quote,
        long startOffset, long endOffset, List<String> rawLocatorIds) {

    public EvidenceDraft {
        rawLocatorIds = List.copyOf(rawLocatorIds);
    }
}
