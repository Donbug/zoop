package com.zoop.ai.http;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.function.Function;

import com.zoop.ai.PipelineJob;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.http.WireJson.Obj;
import tools.jackson.databind.JsonNode;

/** Decoding of the parts the S2 extraction and S3 relation response schemas share. Fails closed with {@link Malformed}. */
final class PipelineWire {
    // The number of receipts has no contract cap (one per runtime call); the response-body size limit is the bound.
    private PipelineWire() {
    }

    /** Wire value of an enum constant: its lower-case name. */
    static String wire(Enum<?> value) {
        return value.name().toLowerCase(Locale.ROOT);
    }

    /** A parser from a wire value to the enum constant whose lower-case name it is. */
    static <E extends Enum<E>> Function<String, Optional<E>> parser(Class<E> type) {
        return value -> {
            for (E constant : type.getEnumConstants()) {
                if (wire(constant).equals(value)) {
                    return Optional.of(constant);
                }
            }
            return Optional.empty();
        };
    }

    static void schema(Obj root, String expected) {
        if (!expected.equals(root.string("schemaVersion", Obj.PRINTABLE))) {
            throw new Malformed(root.path() + ".schemaVersion");
        }
    }

    /** The status's identity is bound to the requested job. */
    static String jobId(Obj root, String expectedJobId) {
        String jobId = root.string("jobId", Obj.PRINTABLE);
        if (!jobId.equals(expectedJobId)) {
            throw new Malformed(root.path() + ".jobId");
        }
        return jobId;
    }

    /** Only replay with an authored recording exists in these families; anything else is a contract violation. */
    static PipelineJob.SourceKind provenance(Obj provenance) {
        if (!"replay".equals(provenance.string("executionMode", Obj.PRINTABLE))
                || !"authored-test".equals(provenance.string("recordingKind", Obj.PRINTABLE))) {
            throw new Malformed(provenance.path() + ".executionMode");
        }
        return provenance.choice("sourceKind", parser(PipelineJob.SourceKind.class));
    }

    static Optional<PipelineJob.Failure> failure(Obj root) {
        return root.optObject("failure").map(f -> new PipelineJob.Failure(f.string("code", Obj.SAFE)));
    }

    static PipelineJob.Dispatch dispatch(Obj dispatch) {
        return new PipelineJob.Dispatch(dispatch.choice("state", parser(PipelineJob.DispatchState.class)), dispatch.count("dispatchCount"),
                dispatch.optChoice("lastOutcome", parser(PipelineJob.Outcome.class)),
                dispatch.optString("lastRuntimeCode", Obj.SAFE), AnalysisWire.stamp(dispatch, "updatedAt"));
    }

    static PipelineJob.Delivery delivery(Obj delivery) {
        PipelineJob.DeliveryState state = delivery.choice("state", parser(PipelineJob.DeliveryState.class));
        Optional<String> reason = delivery.optString("reason", Obj.SAFE);
        if ((state == PipelineJob.DeliveryState.WITHHELD) != reason.isPresent()) {
            throw new Malformed(delivery.path() + ".reason");
        }
        return new PipelineJob.Delivery(state, reason);
    }

    /** The producers withhold every job that is not {@code READY}, so an available delivery of any other state is a contradiction. */
    static void requireDeliveryFitsState(Obj root, PipelineJob.State state, PipelineJob.Delivery delivery) {
        if (delivery.state() == PipelineJob.DeliveryState.AVAILABLE && state != PipelineJob.State.READY) {
            throw new Malformed(root.path() + ".delivery");
        }
    }

    static List<PipelineJob.Receipt> receipts(Obj root) {
        List<PipelineJob.Receipt> receipts = new ArrayList<>();
        for (JsonNode node : root.array("receipts", Integer.MAX_VALUE)) {
            Obj receipt = Obj.of(node, root.path() + ".receipts[]");
            receipts.add(new PipelineJob.Receipt(receipt.string("stage", Obj.SAFE), receipt.string("state", Obj.SAFE),
                    receipt.optString("verdict", Obj.SAFE)));
        }
        return receipts;
    }

    /** The decoded error envelope head. The family decodes its own {@code status} / {@code operation} from {@link #root}. */
    record Rejection(Obj root, String code, boolean retryable, Optional<String> runtimeCode, Optional<String> field) {
        /** The embedded node under {@code name}, or empty when absent or null. */
        Optional<JsonNode> embedded(String name) {
            JsonNode node = root.node().get(name);
            return node == null || node.isNull() ? Optional.empty() : Optional.of(node);
        }
    }

    static Rejection rejection(JsonNode node, String schema, String sentRequestId) {
        Obj root = Obj.of(node, "error");
        schema(root, schema);
        Obj error = root.object("error");
        if (!error.string("requestId", AnalysisWire.REQUEST_ID).equals(sentRequestId)) {
            throw new Malformed("error.requestId");
        }
        return new Rejection(root, error.string("code", AnalysisWire.CODE), error.bool("retryable"),
                error.optString("runtimeCode", AnalysisWire.TEXT), error.optString("field", AnalysisWire.TEXT));
    }
}
