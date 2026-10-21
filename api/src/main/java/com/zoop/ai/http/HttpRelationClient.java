package com.zoop.ai.http;

import java.net.URI;
import java.nio.charset.StandardCharsets;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.RelationServiceErrorException;
import com.zoop.ai.http.AiHttpTransport.Reply;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.relation.RelationAcknowledgement;
import com.zoop.ai.relation.RelationClient;
import com.zoop.ai.relation.RelationJobStatus;
import com.zoop.ai.relation.RelationOperationAcknowledgement;
import com.zoop.ai.relation.RelationOperationStatus;
import com.zoop.ai.relation.RelationResult;
import com.zoop.ai.relation.RelationReviewRequest;
import com.zoop.ai.relation.RelationSubmission;

/**
 * {@link RelationClient} over the shared {@link AiHttpTransport}: HTTP/1.1, no proxy, no redirect, no cookies, no retry, one
 * request per call, bounded response, UTF-8 JSON that echoes the request id. The {@code Idempotency-Key} is the job id for a
 * submit and the operation id for a review. Every response is bound to the requested job id (and operation id); a submit
 * answer must carry the submitted provenance and upstream, and a review answer must echo the exact request (candidate, decision,
 * source version, source revision) it answers.
 */
public final class HttpRelationClient implements RelationClient, AutoCloseable {
    private static final String JOBS = "/internal/v1/relation-jobs";

    private final AiHttpTransport transport;

    public HttpRelationClient(AiClientSettings settings) {
        this.transport = new AiHttpTransport(settings);
    }

    @Override
    public RelationAcknowledgement submit(RelationSubmission submission) {
        String jobId = submission.jobId();
        byte[] body = ("{\"schemaVersion\":\"" + RelationSubmission.SCHEMA_VERSION + "\",\"jobId\":\"" + jobId
                + "\",\"provenance\":{\"sourceKind\":\"" + PipelineWire.wire(submission.sourceKind())
                + "\",\"executionMode\":\"" + submission.executionMode().wire() + "\",\"recordingKind\":\""
                + (submission.executionMode() == com.zoop.ai.ExecutionMode.LIVE ? "provider" : "authored-test") + "\"},\"upstream\":{\"jobId\":\""
                + submission.upstream().jobId() + "\",\"inputDigest\":\"" + submission.upstream().inputDigest() + "\"}}")
                .getBytes(StandardCharsets.UTF_8);
        Reply reply = transport.exchange(AiOperation.SUBMIT, "POST", transport.uri(JOBS), body, jobId, jobRejections(jobId), 200, 202);
        PipelineJob.Disposition disposition = reply.status() == 202 ? PipelineJob.Disposition.NEWLY_ACCEPTED
                : PipelineJob.Disposition.ALREADY_ACCEPTED;
        return new RelationAcknowledgement(disposition, AiHttpTransport.decode(reply, () -> {
            RelationJobStatus status = RelationWire.status(reply.body(), "status", jobId, reply.retryAfter());
            if (status.sourceKind() != submission.sourceKind() || status.executionMode() != submission.executionMode()
                    || !status.upstream().equals(submission.upstream())) {
                throw new Malformed("status.provenance/upstream");
            }
            return status;
        }));
    }

    @Override
    public RelationJobStatus status(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.STATUS, "GET", job(jobId, ""), null, null, jobRejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> RelationWire.status(reply.body(), "status", jobId, reply.retryAfter()));
    }

    @Override
    public RelationResult result(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.RESULT, "GET", job(jobId, "/result"), null, null, jobRejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> RelationWire.result(reply.body(), jobId, reply.retryAfter()));
    }

    @Override
    public RelationJobStatus cancel(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.CANCEL, "POST", job(jobId, "/cancel"), new byte[0], null, jobRejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> RelationWire.status(reply.body(), "status", jobId, reply.retryAfter()));
    }

    @Override
    public RelationAcknowledgement recover(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.RECOVER, "POST", job(jobId, "/recover"), new byte[0], null, jobRejections(jobId), 200, 202);
        PipelineJob.Disposition disposition = reply.status() == 202 ? PipelineJob.Disposition.RECOVERY_ENQUEUED
                : PipelineJob.Disposition.RECOVERY_COALESCED;
        return new RelationAcknowledgement(disposition,
                AiHttpTransport.decode(reply, () -> RelationWire.status(reply.body(), "status", jobId, reply.retryAfter())));
    }

    @Override
    public RelationOperationAcknowledgement review(String jobId, RelationReviewRequest request) {
        PipelineJob.requireId("jobId", jobId);
        String operationId = request.operationId();
        byte[] body = ("{\"relationCandidateId\":\"" + request.relationCandidateId() + "\",\"expectedSourceVersion\":\""
                + request.expectedSourceVersion() + "\",\"expectedSourceRevision\":\"" + request.expectedSourceRevision()
                + "\",\"decision\":\"" + PipelineWire.wire(request.decision()) + "\"}").getBytes(StandardCharsets.UTF_8);
        Reply reply = transport.exchange(AiOperation.REVIEW, "POST", job(jobId, "/reviews"), body, operationId,
                operationRejections(jobId, operationId), 200);
        return new RelationOperationAcknowledgement(RelationOperationAcknowledgement.Disposition.REVIEW_RECORDED_OR_REPLAYED,
                AiHttpTransport.decode(reply, () -> {
                    RelationOperationStatus operation = RelationWire.reviewAccepted(
                            RelationWire.operation(reply.body(), "operation", jobId, operationId, reply.retryAfter()));
                    if (!operation.relationCandidateId().equals(request.relationCandidateId()) || operation.decision() != request.decision()
                            || !operation.expectedSourceVersion().equals(request.expectedSourceVersion())
                            || !operation.expectedSourceRevision().equals(request.expectedSourceRevision())) {
                        throw new Malformed("operation.request");
                    }
                    return operation;
                }));
    }

    @Override
    public RelationOperationStatus operation(String jobId, String operationId) {
        PipelineJob.requireId("jobId", jobId);
        PipelineJob.requireId("operationId", operationId);
        Reply reply = transport.exchange(AiOperation.OPERATION, "GET", operation(jobId, operationId, ""), null, null,
                operationRejections(jobId, operationId), 200);
        return AiHttpTransport.decode(reply, () -> RelationWire.operation(reply.body(), "operation", jobId, operationId, reply.retryAfter()));
    }


    @Override
    public void close() {
        transport.close();
    }

    private URI job(String jobId, String suffix) {
        return transport.uri(JOBS + "/" + AiHttpTransport.segment(jobId) + suffix);
    }

    private URI operation(String jobId, String operationId, String suffix) {
        return job(jobId, "/reviews/" + AiHttpTransport.segment(operationId) + suffix);
    }

    /** Job operations: an envelope that embeds a review operation is not something these routes produce. */
    private static AiHttpTransport.Rejections jobRejections(String jobId) {
        return (document, status, retryAfter, operation, requestId) -> {
            PipelineWire.Rejection rejection = RelationWire.rejection(document, requestId);
            return new RelationServiceErrorException(operation, requestId, status, rejection.code(), rejection.retryable(),
                    rejection.runtimeCode(), rejection.field(), retryAfter, RelationWire.embeddedStatus(rejection, jobId, retryAfter),
                    RelationWire.embeddedOperation(rejection, jobId, null, retryAfter));
        };
    }

    private static AiHttpTransport.Rejections operationRejections(String jobId, String operationId) {
        return (document, status, retryAfter, operation, requestId) -> {
            PipelineWire.Rejection rejection = RelationWire.rejection(document, requestId);
            return new RelationServiceErrorException(operation, requestId, status, rejection.code(), rejection.retryable(),
                    rejection.runtimeCode(), rejection.field(), retryAfter, RelationWire.embeddedStatus(rejection, jobId, retryAfter),
                    RelationWire.embeddedOperation(rejection, jobId, operationId, retryAfter));
        };
    }
}
