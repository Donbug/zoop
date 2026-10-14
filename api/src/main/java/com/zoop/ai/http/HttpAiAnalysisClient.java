package com.zoop.ai.http;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Optional;

import com.zoop.ai.AiAnalysisClient;
import com.zoop.ai.AiClientException;
import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiServiceErrorException;
import com.zoop.ai.AnalysisAcknowledgement;
import com.zoop.ai.AnalysisAcknowledgement.Disposition;
import com.zoop.ai.AnalysisJobStatus;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.AnalysisSubmission;
import com.zoop.ai.http.AiHttpTransport.Reply;
import com.zoop.ai.http.WireJson.Malformed;
import tools.jackson.databind.JsonNode;

/**
 * {@link AiAnalysisClient} over the shared {@link AiHttpTransport} (HTTP/1.1, no proxy, no redirect, no cookies, no
 * authenticator).
 *
 * <p>One call is one request: there is no automatic retry. The bearer token is sent only to the configured base URI. A call
 * is bounded by the connect timeout, a total request deadline and a response size limit. The request id is the current
 * {@code requestId} MDC value (set by {@code RequestIdFilter}) when it fits the AI contract
 * ({@code [A-Za-z0-9._-]{1,128}}), otherwise a fresh UUID; an unsafe or oversized inbound id is never forwarded. The
 * {@code Idempotency-Key} is always the job id, never the request id. The response must echo the request id.
 */
public final class HttpAiAnalysisClient implements AiAnalysisClient, AutoCloseable {
    private static final String JOBS = "/internal/v1/analysis-jobs";

    private final AiHttpTransport transport;

    public HttpAiAnalysisClient(AiClientSettings settings) {
        this.transport = new AiHttpTransport(settings);
    }

    @Override
    public AnalysisAcknowledgement submit(AnalysisSubmission submission) {
        byte[] body = submitBody(submission);
        String jobId = submission.jobId();
        Reply reply = transport.exchange(AiOperation.SUBMIT, "POST", transport.uri(JOBS), body, jobId, rejections(jobId), 200, 202);
        Disposition disposition = reply.status() == 202 ? Disposition.NEWLY_ACCEPTED : Disposition.ALREADY_ACCEPTED;
        return new AnalysisAcknowledgement(disposition, AiHttpTransport.decode(reply, () -> {
            AnalysisJobStatus status = AnalysisWire.status(reply.body(), "status", jobId, reply.retryAfter());
            if (status.kind() != submission.kind() || status.mode() != submission.mode()) {
                throw new Malformed("status.kind/mode");
            }
            return status;
        }));
    }

    @Override
    public AnalysisJobStatus status(String jobId) {
        AnalysisSubmission.requireJobId(jobId);
        Reply reply = transport.exchange(AiOperation.STATUS, "GET", transport.uri(JOBS + "/" + AiHttpTransport.segment(jobId)), null,
                null, rejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> AnalysisWire.status(reply.body(), "status", jobId, reply.retryAfter()));
    }

    @Override
    public AnalysisResult result(String jobId) {
        AnalysisSubmission.requireJobId(jobId);
        Reply reply = transport.exchange(AiOperation.RESULT, "GET",
                transport.uri(JOBS + "/" + AiHttpTransport.segment(jobId) + "/result"), null, null, rejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> AnalysisWire.result(reply.body(), jobId, reply.retryAfter()));
    }

    @Override
    public AnalysisJobStatus cancel(String jobId) {
        AnalysisSubmission.requireJobId(jobId);
        Reply reply = transport.exchange(AiOperation.CANCEL, "POST",
                transport.uri(JOBS + "/" + AiHttpTransport.segment(jobId) + "/cancel"), new byte[0], null, rejections(jobId), 200);
        return AiHttpTransport.decode(reply, () -> AnalysisWire.status(reply.body(), "status", jobId, reply.retryAfter()));
    }

    @Override
    public AnalysisAcknowledgement recover(String jobId) {
        AnalysisSubmission.requireJobId(jobId);
        Reply reply = transport.exchange(AiOperation.RECOVER, "POST",
                transport.uri(JOBS + "/" + AiHttpTransport.segment(jobId) + "/recover"), new byte[0], null, rejections(jobId), 200, 202);
        Disposition disposition = reply.status() == 202 ? Disposition.RECOVERY_ENQUEUED : Disposition.RECOVERY_COALESCED;
        return new AnalysisAcknowledgement(disposition,
                AiHttpTransport.decode(reply, () -> AnalysisWire.status(reply.body(), "status", jobId, reply.retryAfter())));
    }

    @Override
    public void close() {
        transport.close();
    }

    // ---- request construction ----

    private static byte[] submitBody(AnalysisSubmission submission) {
        String input = objectText("inputJson", submission.inputJson());
        String provenance = objectText("provenanceJson", submission.provenanceJson());
        String body = "{\"schemaVersion\":\"" + AnalysisSubmission.SCHEMA_VERSION + "\",\"jobId\":\"" + submission.jobId()
                + "\",\"kind\":\"" + submission.kind().wire() + "\",\"mode\":\"" + submission.mode().wire()
                + "\",\"input\":" + input + ",\"provenance\":" + provenance + "}";
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > AiClientSettings.MAX_REQUEST_BYTES) {
            throw new IllegalArgumentException("submission exceeds " + AiClientSettings.MAX_REQUEST_BYTES + " bytes");
        }
        return bytes;
    }

    private static String objectText(String name, String json) {
        try {
            WireJson.parse(json, name);
        } catch (Malformed error) {
            throw new IllegalArgumentException(name + " must be one JSON object without duplicate keys");
        }
        return json.strip();
    }

    // ---- error envelope ----

    private static AiHttpTransport.Rejections rejections(String jobId) {
        return (document, status, retryAfter, operation, requestId) -> rejection(document, status, retryAfter, operation, requestId, jobId);
    }

    private static AiClientException rejection(JsonNode document, int status, Optional<Duration> retryAfter, AiOperation operation,
                                               String requestId, String jobId) {
        AnalysisWire.Rejection rejection = AnalysisWire.rejection(document, jobId, retryAfter);
        if (!rejection.requestId().equals(requestId)) {
            throw new Malformed("error.requestId");
        }
        return new AiServiceErrorException(operation, requestId, status, rejection.code(), rejection.retryable(),
                rejection.runtimeCode(), rejection.field(), retryAfter, rejection.status());
    }
}
