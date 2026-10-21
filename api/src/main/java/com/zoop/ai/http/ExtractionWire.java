package com.zoop.ai.http;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import com.zoop.ai.PipelineJob;
import com.zoop.ai.extraction.ExtractionJobStatus;
import com.zoop.ai.extraction.ExtractionResult;
import com.zoop.ai.extraction.UntrustedExtractionPayload;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.http.WireJson.Obj;
import tools.jackson.databind.JsonNode;

/** Typed decoding of the S2 extraction documents (schema {@code zoop-ai-internal-extraction-1}). Fails closed with {@link Malformed}. */
final class ExtractionWire {
    static final String SCHEMA = "zoop-ai-internal-extraction-1";
    private static final int MAX_STAGES = 8;
    private static final int MAX_CANDIDATES = 100_000;

    private ExtractionWire() {
    }

    /** {@code ExtractionJobStatus}: every key required, identity bound to the requested job. */
    static ExtractionJobStatus status(JsonNode node, String path, String expectedJobId, Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, path);
        PipelineWire.schema(root, SCHEMA);
        String jobId = PipelineWire.jobId(root, expectedJobId);
        Obj usage = root.object("usage");
        List<ExtractionJobStatus.Stage> stages = new ArrayList<>();
        for (JsonNode item : root.array("stages", MAX_STAGES)) {
            Obj stage = Obj.of(item, path + ".stages[]");
            stages.add(new ExtractionJobStatus.Stage(stage.choice("stage", PipelineWire.parser(ExtractionJobStatus.StageName.class)),
                    stage.choice("state", PipelineWire.parser(ExtractionJobStatus.StageState.class))));
        }
        PipelineJob.State state = root.choice("state", PipelineWire.parser(PipelineJob.State.class));
        PipelineJob.Delivery delivery = PipelineWire.delivery(root.object("delivery"));
        PipelineWire.requireDeliveryFitsState(root, state, delivery);
        PipelineJob.Provenance provenance = PipelineWire.provenance(root.object("provenance"));
        return new ExtractionJobStatus(
                jobId,
                root.string("inputDigest", Obj.SHA256),
                root.object("approval").string("approvedRequestDigest", Obj.SHA256),
                provenance.sourceKind(),
                provenance.executionMode(),
                state,
                root.string("phase", Obj.SAFE),
                root.choice("resumeMode", PipelineWire.parser(PipelineJob.ResumeMode.class)),
                PipelineWire.failure(root),
                new ExtractionJobStatus.Usage(usage.count("replayCalls"), usage.count("startedWithoutReceipt"),
                        usage.count("providerCalls"), usage.count("paidModelCalls"), usage.count("receivedCalls"), usage.count("unsentCalls"),
                        Optional.ofNullable(usage.optCount("inputTokens")), Optional.ofNullable(usage.optCount("outputTokens")),
                        Optional.ofNullable(usage.optCount("reasoningTokens")), usage.optString("estimatedUsd", Obj.SAFE),
                        usage.optString("chargedUsd", Obj.SAFE)),
                stages,
                delivery,
                PipelineWire.dispatch(root.object("dispatch")),
                root.choice("next", PipelineWire.parser(PipelineJob.Next.class)),
                AnalysisWire.stamp(root, "acceptedAt"),
                AnalysisWire.stamp(root, "observedAt"),
                retryAfter);
    }

    /** {@code ExtractionResultEnvelope}. The job content is present exactly when delivery is {@code available}. */
    static ExtractionResult result(JsonNode node, String expectedJobId, Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, "result");
        PipelineWire.schema(root, SCHEMA);
        ExtractionJobStatus status = status(root.raw("status"), "result.status", expectedJobId, retryAfter);
        PipelineJob.Delivery delivery = PipelineWire.delivery(root.object("delivery"));
        if (!delivery.equals(status.delivery())) {
            throw new Malformed("result.delivery");
        }
        Optional<Obj> job = root.optObject("job");
        if ((delivery.state() == PipelineJob.DeliveryState.AVAILABLE) != job.isPresent()) {
            throw new Malformed("result.job");
        }
        return new ExtractionResult(status, delivery, job.map(content -> payload(content, status)), PipelineWire.receipts(root));
    }

    private static UntrustedExtractionPayload payload(Obj job, ExtractionJobStatus status) {
        if (!status.jobId().equals(job.string("jobId", Obj.PRINTABLE)) || !status.inputDigest().equals(job.string("inputDigest", Obj.SHA256))) {
            throw new Malformed("result.job");
        }
        job.object("counts");
        job.array("eventCandidates", MAX_CANDIDATES);
        job.array("topicCandidates", MAX_CANDIDATES);
        return new UntrustedExtractionPayload(status.jobId(), status.inputDigest(), WireJson.compact(job.node()));
    }

    /** The error envelope; its embedded {@code status} (if any) must describe the requested job. */
    static PipelineWire.Rejection rejection(JsonNode node, String requestId) {
        return PipelineWire.rejection(node, SCHEMA, requestId);
    }

    static Optional<ExtractionJobStatus> embeddedStatus(PipelineWire.Rejection rejection, String expectedJobId, Optional<Duration> retryAfter) {
        return rejection.embedded("status").map(embedded -> status(embedded, "error.status", expectedJobId, retryAfter));
    }
}
