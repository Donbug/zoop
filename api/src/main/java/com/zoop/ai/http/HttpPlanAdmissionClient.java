package com.zoop.ai.http;

import java.nio.charset.StandardCharsets;
import java.util.Objects;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.PlanAdmissionServiceErrorException;
import com.zoop.ai.plan.PlanAdmission;
import com.zoop.ai.plan.PlanAdmissionClient;
import com.zoop.ai.plan.PlanReference;

/** Existing bounded, no-proxy/no-redirect/no-retry AI transport. Admission and query never execute a unit. */
public final class HttpPlanAdmissionClient implements PlanAdmissionClient, AutoCloseable {
    private static final String ADMISSIONS = "/internal/v1/plan-admissions";
    private final AiHttpTransport transport;

    public HttpPlanAdmissionClient(AiClientSettings settings) {
        transport = new AiHttpTransport(settings);
    }

    @Override
    public PlanAdmission admit(PlanReference reference) {
        Objects.requireNonNull(reference, "reference");
        byte[] body = ("{\"schemaVersion\":\"" + PlanReference.SCHEMA_VERSION + "\",\"planId\":\"" + reference.planId()
                + "\",\"planDigest\":\"" + reference.planDigest() + "\"}").getBytes(StandardCharsets.UTF_8);
        var reply = transport.exchange(AiOperation.PLAN_ADMIT, "POST", transport.uri(ADMISSIONS), body, reference.planId(), rejections(), 200, 201);
        return AiHttpTransport.decode(reply, () -> PlanAdmissionWire.admission(reply.body(), reference));
    }

    @Override
    public PlanAdmission status(PlanReference reference) {
        Objects.requireNonNull(reference, "reference");
        var reply = transport.exchange(AiOperation.STATUS, "GET", transport.uri(ADMISSIONS + "/" + reference.planId()
                + "?planDigest=" + reference.planDigest()), null, null, rejections(), 200);
        return AiHttpTransport.decode(reply, () -> PlanAdmissionWire.admission(reply.body(), reference));
    }

    @Override
    public void close() {
        transport.close();
    }

    private static AiHttpTransport.Rejections rejections() {
        return (document, status, retryAfter, operation, requestId) -> {
            var rejection = PlanAdmissionWire.rejection(document, requestId);
            return new PlanAdmissionServiceErrorException(operation, requestId, status, rejection.code(), rejection.retryable(),
                    rejection.runtimeCode(), rejection.field(), retryAfter);
        };
    }
}
