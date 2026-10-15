package com.zoop.document.evidence.repository;

/** The scope of an analysis found by its AI job id; its status and result are deliberately not read. */
public record AnalysisIdentity(String id, String articleId, String articleVersion, String stage, String companyId) {
}
