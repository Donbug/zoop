package com.zoop.ai.relation;

import java.util.Objects;
import java.util.regex.Pattern;

import com.zoop.ai.PipelineJob;

/**
 * One review decision on one relation candidate of one S3 job, with the AI <b>source</b> expectations the service compares
 * atomically: {@code expectedSourceVersion} is the job's {@code inputDigest} and {@code expectedSourceRevision} is the
 * candidate's runtime event-chain revision, both exactly as read from the delivered result. Neither is the application's own
 * review {@code expectedRevision} and this record has no field for it: an app revision must never be forwarded here.
 *
 * <p>{@code operationId} is the stable id of this one operation and becomes the {@code Idempotency-Key}. A retry after an
 * ambiguous outcome must reuse the same id and the same body (the service answers 200 with the existing operation) and must
 * never mint a new id for the same decision. The reviewer is the authenticated principal; there is no field to send one.
 */
public record RelationReviewRequest(String operationId, String relationCandidateId, String expectedSourceVersion,
                                    String expectedSourceRevision, RelationDecision decision) {
    public static final Pattern CANDIDATE_ID = Pattern.compile("rc-[a-f0-9]{64}");
    /** A reviewable revision is at least 1 (a candidate with no pipeline event yet reports 0 and cannot be reviewed). */
    public static final Pattern SOURCE_REVISION = Pattern.compile("[1-9][0-9]{0,8}");

    public RelationReviewRequest {
        PipelineJob.requireId("operationId", operationId);
        if (relationCandidateId == null || !CANDIDATE_ID.matcher(relationCandidateId).matches()) {
            throw new IllegalArgumentException("relationCandidateId must match " + CANDIDATE_ID.pattern());
        }
        PipelineJob.requireDigest("expectedSourceVersion", expectedSourceVersion);
        if (expectedSourceRevision == null || !SOURCE_REVISION.matcher(expectedSourceRevision).matches()) {
            throw new IllegalArgumentException("expectedSourceRevision must match " + SOURCE_REVISION.pattern());
        }
        Objects.requireNonNull(decision, "decision");
    }

    /** The request for a candidate exactly as a delivered result reported it (its job-bound source version and revision). */
    public static RelationReviewRequest of(String operationId, UntrustedRelationPayload.Candidate candidate, RelationDecision decision) {
        return new RelationReviewRequest(operationId, candidate.relationCandidateId(), candidate.sourceVersion(),
                candidate.sourceRevision(), decision);
    }
}
