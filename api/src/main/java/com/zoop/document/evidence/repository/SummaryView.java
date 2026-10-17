package com.zoop.document.evidence.repository;

/** One summary {@code document_analyses} row with its stored result text (null unless the row is available). */
public record SummaryView(String id, String articleId, String articleVersion, String stage, String companyId, String status,
        long requestNo, String grantReference, String grantRevision, String aiJobId, String resultVersion,
        String resultArtifactId, String exactReceiptId, String semanticReceiptId, String resultJson) {
}
