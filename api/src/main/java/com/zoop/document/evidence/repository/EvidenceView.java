package com.zoop.document.evidence.repository;

/** One {@code evidence} row as stored; offsets are Unicode code points (end exclusive). */
public record EvidenceView(String id, String articleId, String articleVersion, String textArtifactId, String quote,
        long startOffset, long endOffset, String inputKind, Boolean quoteVerified, String verificationArtifactId) {
}
