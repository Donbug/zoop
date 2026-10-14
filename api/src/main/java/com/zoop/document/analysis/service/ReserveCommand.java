package com.zoop.document.analysis.service;

import java.time.Instant;

import com.zoop.document.analysis.AnalysisStage;

/**
 * Everything the single reserving transaction needs. Nothing in it is read from the database by the caller as a decision
 * that the transaction would not repeat: the article, version, text artifact, company and latest request are re-read under
 * the article lock.
 *
 * @param companyId      the operator-declared company; only a sentiment stores it in {@code company_id}
 * @param companyName    the catalog name frozen into the submit; it must still be the catalog's name
 * @param expectedLatest the compare-and-set value: the id of the latest request of the scope, or null for "none yet"
 * @param textArtifactId the {@code text-<version>} artifact the submit's document came from
 * @param textSha256     SHA-256 of the UTF-8 text in the submit: it must be the registered text artifact's hash
 * @param grantCheckedAt when the flat registry was read for this request
 * @param submit         the already stored {@code ai_submit} file
 */
public record ReserveCommand(String analysisId, String aiJobId, String articleId, String articleVersion, AnalysisStage stage,
        String companyId, String companyName, String expectedLatest, String grantId, String grantRevision,
        Instant grantCheckedAt, String textArtifactId, String textSha256, long textBytes, ArtifactFile submit) {
}
