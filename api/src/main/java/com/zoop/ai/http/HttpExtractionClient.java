package com.zoop.ai.http;

import java.nio.charset.StandardCharsets;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.ExtractionServiceErrorException;
import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionAcknowledgement;
import com.zoop.ai.extraction.ExtractionClient;
import com.zoop.ai.extraction.ExtractionJobStatus;
import com.zoop.ai.extraction.ExtractionResult;
import com.zoop.ai.extraction.ExtractionSubmission;
import com.zoop.ai.http.AiHttpTransport.Reply;
import com.zoop.ai.http.WireJson.Malformed;

/**
 * {@link ExtractionClient} over the shared {@link AiHttpTransport}: HTTP/1.1, no proxy, no redirect, no cookies, no retry, one
 * request per call, bounded response, UTF-8 JSON that echoes the request id. The {@code Idempotency-Key} is the job id. Every
 * response is bound to the requested job id; a submit answer must also carry the approved request digest that was sent.
 */
public final class HttpExtractionClient implements ExtractionClient, AutoCloseable {
    private static final String JOBS = "/internal/v1/extraction-jobs";

    private final AiHttpTransport transport;

    public HttpExtractionClient(AiClientSettings settings) {
        this.transport = new AiHttpTransport(settings);
    }

    @Override
    public ExtractionAcknowledgement submit(ExtractionSubmission submission) {
        String jobId = submission.jobId();
        byte[] body = ("{\"schemaVersion\":\"" + ExtractionSubmission.SCHEMA_VERSION + "\",\"jobId\":\"" + jobId
                + "\",\"approvedRequestDigest\":\"" + submission.approvedRequestDigest() + "\"}").getBytes(StandardCharsets.UTF_8);
        Reply reply = transport.exchange(AiOperation.SUBMIT, "POST", transport.uri(JOBS), body, jobId, rejections(jobId), 200, 202);
        PipelineJob.Disposition disposition = reply.status() == 202 ? PipelineJob.Disposition.NEWLY_ACCEPTED
                : PipelineJob.Disposition.ALREADY_ACCEPTED;
        return new ExtractionAcknowledgement(disposition, AiHttpTransport.decode(reply, () -> {
            ExtractionJobStatus status = ExtractionWire.status(reply.body(), "status", jobId, reply.retryAfter());
            if (!status.approvedRequestDigest().equals(submission.approvedRequestDigest()) || status.executionMode() != submission.executionMode()) {
                throw new Malformed("status.approval");
            }
            return status;
        }));
    }

    @Override
    public ExtractionJobStatus status(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.STATUS, "GET", job(jobId, ""), null, null, rejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> ExtractionWire.status(reply.body(), "status", jobId, reply.retryAfter()));
    }

    @Override
    public ExtractionResult result(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.RESULT, "GET", job(jobId, "/result"), null, null, rejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> ExtractionWire.result(reply.body(), jobId, reply.retryAfter()));
    }

    @Override
    public ExtractionJobStatus cancel(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.CANCEL, "POST", job(jobId, "/cancel"), new byte[0], null, rejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> ExtractionWire.status(reply.body(), "status", jobId, reply.retryAfter()));
    }

    @Override
    public ExtractionAcknowledgement recover(String jobId) {
        PipelineJob.requireId("jobId", jobId);
        Reply reply = transport.exchange(AiOperation.RECOVER, "POST", job(jobId, "/recover"), new byte[0], null, rejections(jobId), 200, 202);
        PipelineJob.Disposition disposition = reply.status() == 202 ? PipelineJob.Disposition.RECOVERY_ENQUEUED
                : PipelineJob.Disposition.RECOVERY_COALESCED;
        return new ExtractionAcknowledgement(disposition,
                AiHttpTransport.decode(reply, () -> ExtractionWire.status(reply.body(), "status", jobId, reply.retryAfter())));
    }

    @Override
    public void close() {
        transport.close();
    }

    private java.net.URI job(String jobId, String suffix) {
        return transport.uri(JOBS + "/" + AiHttpTransport.segment(jobId) + suffix);
    }

    private static AiHttpTransport.Rejections rejections(String jobId) {
        return (document, status, retryAfter, operation, requestId) -> {
            PipelineWire.Rejection rejection = ExtractionWire.rejection(document, requestId);
            return new ExtractionServiceErrorException(operation, requestId, status, rejection.code(), rejection.retryable(),
                    rejection.runtimeCode(), rejection.field(), retryAfter, ExtractionWire.embeddedStatus(rejection, jobId, retryAfter));
        };
    }
}
