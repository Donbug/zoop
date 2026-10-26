package com.zoop.admin.review;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * The {@code listAnalysisCandidates}/{@code getAnalysisCandidate} response shapes ({@code docs/api/openapi.yaml}). One candidate
 * is one S2 event candidate with its S3 relations, or one S3 relation without an event (PR #345). Values the AI source does not
 * produce are null rather than invented: {@code policyVersion}, {@code rule} (not evaluated yet), a company's app id.
 */
public final class AnalysisCandidates {
    private AnalysisCandidates() {
    }

    public record CandidateList(List<CandidateRow> items, String nextCursor, Map<String, Integer> counts, Instant asOf) {
    }

    /** {@code companyId} is the app company id, null while the source company is not mapped to one; {@code role} may be null. */
    public record CandidateCompany(String companyId, String name, String role) {
    }

    public record CandidateRow(String title, String candidateId, String issueId, String status, boolean active,
            String policyVersion, String action, String target, String eventTime, List<CandidateCompany> companies,
            List<String> relationTypes, int evidenceCount, List<String> reasons, boolean onUserGraph,
            ReviewDecisionOut decision, Object rule) {
    }

    public record ReviewDecisionOut(long id, String targetType, String targetId, String decision, String reason,
            String adminEmail, Instant decidedAt, long revision, String origin) {
    }

    public record CandidateMention(String title, String mentionId, String action, String target, String eventTime,
            String period, String assertionStatus, boolean background, List<String> countries, List<String> keywords,
            List<CandidateCompany> participants) {
    }

    public record CandidateArticle(String title, String articleId, String publisher, String url, String publishedAt) {
    }

    /** {@code quote} is null when the article's access was withdrawn; {@code articleTitle}/{@code url} when the app lacks it. */
    public record CandidateEvidence(String articleId, String articleVersion, int start, int end, String quote,
            String articleTitle, String url) {
    }

    public record CandidateRelation(String relationId, String sourceVersion, String sourceRevision, String relationType,
            String source, String target, String role, String assertionStatus, int evidenceCount, boolean onUserGraph,
            ReviewDecisionOut decision) {
    }

    public record VerdictOut(String target, String decision, String reason) {
    }

    public record VerificationOut(String provider, String model, String verifierVersion, Map<String, Double> decisionPolicy,
            List<VerdictOut> verdicts, List<Object> fieldVerdicts, List<Object> observations) {
    }

    public record CandidateDetail(String title, String candidateId, String sourceVersion, String sourceRevision,
            String issueId, String status, boolean active, String policyVersion, String action, String target,
            String eventTime, List<CandidateCompany> companies, List<String> relationTypes, int evidenceCount,
            List<String> reasons, boolean onUserGraph, ReviewDecisionOut decision, Object rule, CandidateMention mention,
            List<CandidateArticle> articles, List<CandidateEvidence> evidence, List<CandidateRelation> relations,
            VerificationOut verification, String invalidationReason, List<ReviewDecisionOut> history, String graphDb) {
    }
}
