package com.zoop.admin.review;

import java.util.Locale;

import com.zoop.ai.AiServiceRejectionException;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationDecision;
import com.zoop.ai.relation.RelationOperationStatus;
import com.zoop.ai.relation.RelationReviewRequest;

/**
 * {@link RelationReviewClient} over the S3 transport {@link RelationClient} (internal AI contract, relation review). It only
 * translates: the AI error codes go through {@link Refusal#of}, and a failure without an AI answer is grouped by what the app may
 * conclude from it.
 * <ul>
 * <li>Never sent (the connection could not be made, {@code requestMaybeProcessed=false}): {@link Refusal#UNAVAILABLE}, nothing was
 *     recorded.</li>
 * <li>Sent but not answered (timeout, I/O, an undecodable 5xx): {@link Refusal#UNCONFIRMED}, the same request is sent again.</li>
 * <li>A 200 whose body is not the operation of this request: {@link Refusal#CONTRACT}, settled only by an operation lookup.</li>
 * <li>A stored command the contract cannot carry (an id, version or revision out of its pattern): {@link Refusal#INELIGIBLE}, a
 *     definite refusal. Nothing was sent, so nothing is or ever will be recorded; a lookup of it is not found.</li>
 * </ul>
 */
public final class AiRelationReviewClient implements RelationReviewClient {
    static final String NOT_SENT = "relation_review_not_sent";
    static final String UNANSWERED = "relation_review_unanswered";
    static final String LOOKUP_UNANSWERED = "relation_review_lookup_unanswered";
    static final String MALFORMED = "relation_review_response_malformed";
    static final String REQUEST_INVALID = "relation_review_request_invalid";
    private static final String OPERATION_NOT_FOUND = "operation_not_found";

    private final RelationClient relations;

    public AiRelationReviewClient(RelationClient relations) {
        this.relations = relations;
    }

    @Override
    public void review(String sourceJobId, String relationCandidateId, String expectedSourceVersion, String expectedSourceRevision,
            String decision, String operationId) {
        RelationReviewRequest request;
        try {
            PipelineJob.requireId("jobId", sourceJobId);
            request = new RelationReviewRequest(operationId, relationCandidateId, expectedSourceVersion, expectedSourceRevision,
                    RelationDecision.valueOf(decision.toUpperCase(Locale.ROOT)));
        } catch (IllegalArgumentException | NullPointerException invalid) {
            throw invalidCommand();
        }
        try {
            relations.review(sourceJobId, request);
        } catch (AiServiceRejectionException rejected) {
            throw new Refused(rejected.code());
        } catch (AiTransportException failed) {
            throw failed.failure() == AiTransportException.Failure.RESPONSE_MALFORMED ? new Refused(Refusal.CONTRACT, MALFORMED)
                    : failed.requestMaybeProcessed() ? new Refused(Refusal.UNCONFIRMED, UNANSWERED)
                    : new Refused(Refusal.UNAVAILABLE, NOT_SENT);
        } catch (IllegalArgumentException unreadable) {
            // Raised after sending (decoding the answer): it may be recorded, so only a lookup settles it.
            throw new Refused(Refusal.CONTRACT, MALFORMED);
        }
    }

    @Override
    public Operation lookup(String sourceJobId, String operationId) {
        try {
            PipelineJob.requireId("jobId", sourceJobId);
            PipelineJob.requireId("operationId", operationId);
        } catch (IllegalArgumentException | NullPointerException invalid) {
            // An id the contract rejects was never sent, so nothing can be recorded under it.
            return Operation.notFound();
        }
        RelationOperationStatus status;
        try {
            status = relations.operation(sourceJobId, operationId);
        } catch (AiServiceRejectionException rejected) {
            if (OPERATION_NOT_FOUND.equals(rejected.code())) return Operation.notFound();
            throw new Refused(rejected.code());
        } catch (AiTransportException failed) {
            // A read: it changed nothing, whatever failed.
            throw new Refused(Refusal.UNAVAILABLE, LOOKUP_UNANSWERED);
        } catch (IllegalArgumentException unreadable) {
            throw new Refused(Refusal.CONTRACT, MALFORMED);
        }
        Lookup state = status.review().state() == RelationOperationStatus.ReviewState.APPLIED ? Lookup.RECORDED
                : Lookup.UNCONFIRMED;
        boolean current = status.limitation().filter(RelationOperationStatus.Limitation.REVIEW_CONTRACT_CHANGED::equals).isEmpty();
        return new Operation(state, status.jobId(), status.relationCandidateId(), status.decision().name(),
                status.expectedSourceVersion(), status.expectedSourceRevision(), current);
    }

    private static Refused invalidCommand() {
        return new Refused(Refusal.INELIGIBLE, REQUEST_INVALID);
    }
}
