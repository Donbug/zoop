package com.zoop.ai.http;

import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.regex.Pattern;

import com.zoop.ai.AnalysisJobStatus;
import com.zoop.ai.AnalysisJobStatus.Dispatch;
import com.zoop.ai.AnalysisKind;
import com.zoop.ai.AnalysisResult;
import com.zoop.ai.ExecutionMode;
import com.zoop.ai.UntrustedAnalysisPayload;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.http.WireJson.Obj;
import tools.jackson.databind.JsonNode;

/** Typed decoding of the internal transport documents (schema {@code zoop-ai-internal-1}). Fails closed with {@link Malformed}. */
final class AnalysisWire {
    static final String INTERNAL_SCHEMA = "zoop-ai-internal-1";
    private static final Pattern CODE = Pattern.compile("[a-z][a-z0-9_]{0,63}");
    private static final Pattern RECEIPT_STAMP = Pattern.compile(
            "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?(Z|[+-][0-9]{2}:[0-9]{2})");
    private static final Pattern TEXT = Pattern.compile("[\\x20-\\x7E]{1,200}");
    private static final Pattern STAMP = Pattern.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z");
    private static final Pattern REQUEST_ID = Pattern.compile("[A-Za-z0-9._-]{1,128}");
    private static final int MAX_ARTIFACTS = 64;
    private static final int MAX_RECEIPTS = 64;

    private AnalysisWire() {
    }

    static boolean validRequestId(String value) {
        return value != null && REQUEST_ID.matcher(value).matches();
    }

    static Instant stamp(Obj obj, String name) {
        try {
            return Instant.parse(obj.string(name, STAMP));
        } catch (DateTimeParseException error) {
            throw new Malformed(obj.path() + "." + name);
        }
    }

    /** Receipt times come from the runtime ledger: ISO-8601 with microseconds and an explicit offset ({@code ...+00:00}). */
    private static Instant offsetStamp(Obj obj, String name) {
        return parseOffset(obj, name, obj.string(name, RECEIPT_STAMP));
    }

    private static Optional<Instant> optOffsetStamp(Obj obj, String name) {
        return obj.optString(name, RECEIPT_STAMP).map(value -> parseOffset(obj, name, value));
    }

    private static Instant parseOffset(Obj obj, String name, String value) {
        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeParseException error) {
            throw new Malformed(obj.path() + "." + name);
        }
    }

    private static void schema(Obj root, String expected) {
        if (!expected.equals(root.string("schemaVersion", Obj.PRINTABLE))) {
            throw new Malformed(root.path() + ".schemaVersion");
        }
    }

    /** {@code JobStatus}: every key required, identity bound to the requested job. */
    static AnalysisJobStatus status(JsonNode node, String path, String expectedJobId, Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, path);
        schema(root, INTERNAL_SCHEMA);
        String jobId = root.string("jobId", Obj.PRINTABLE);
        if (!jobId.equals(expectedJobId)) {
            throw new Malformed(path + ".jobId");
        }
        Optional<Obj> failure = root.optObject("failure");
        Obj usage = root.object("usage");
        Obj dispatch = root.object("dispatch");
        return new AnalysisJobStatus(
                jobId,
                root.choice("kind", AnalysisKind::fromWire),
                root.choice("mode", ExecutionMode::fromWire),
                root.string("inputDigest", Obj.SHA256),
                root.choice("state", AnalysisJobStatus.State::fromWire),
                root.string("phase", Obj.SAFE),
                root.choice("resumeMode", AnalysisJobStatus.ResumeMode::fromWire),
                failure.map(f -> new AnalysisJobStatus.Failure(f.string("code", Obj.SAFE),
                        f.optChoice("stage", AnalysisKind::fromWire))).orElse(null),
                root.strings("artifactIds", MAX_ARTIFACTS, Obj.PRINTABLE),
                new AnalysisJobStatus.Usage(usage.count("providerAttempts"), usage.count("replayCalls"),
                        usage.optCount("inputTokens"), usage.optCount("outputTokens"), usage.optCount("cachedTokens"),
                        usage.optCount("reasoningTokens"), usage.optNumber("cost")),
                (int) Math.min(root.count("unreceiptedAttempts"), Integer.MAX_VALUE),
                new Dispatch(dispatch.choice("state", Dispatch.DispatchState::fromWire),
                        dispatch.optChoice("command", Dispatch.Command::fromWire), dispatch.count("dispatchCount"),
                        dispatch.optChoice("lastOutcome", Dispatch.Outcome::fromWire),
                        dispatch.optString("lastRuntimeCode", Obj.PRINTABLE), stamp(dispatch, "updatedAt")),
                root.choice("next", AnalysisJobStatus.Next::fromWire),
                stamp(root, "acceptedAt"),
                stamp(root, "observedAt"),
                retryAfter);
    }

    /** {@code ResultEnvelope}. The job payload is present exactly when delivery is {@code available}. */
    static AnalysisResult result(JsonNode node, String expectedJobId, Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, "result");
        schema(root, INTERNAL_SCHEMA);
        AnalysisJobStatus status = status(root.raw("status"), "result.status", expectedJobId, retryAfter);
        Obj delivery = root.object("delivery");
        String state = delivery.string("state", Obj.PRINTABLE);
        Optional<String> reason = delivery.optString("reason", Obj.SAFE);
        AnalysisResult.Delivery.State deliveryState = switch (state) {
            case "available" -> AnalysisResult.Delivery.State.AVAILABLE;
            case "withheld" -> AnalysisResult.Delivery.State.WITHHELD;
            default -> throw new Malformed("result.delivery.state");
        };
        if ((deliveryState == AnalysisResult.Delivery.State.WITHHELD) != reason.isPresent()) {
            throw new Malformed("result.delivery.reason");
        }
        Optional<Obj> job = root.optObject("job");
        if ((deliveryState == AnalysisResult.Delivery.State.AVAILABLE) != job.isPresent()) {
            throw new Malformed("result.job");
        }
        Optional<UntrustedAnalysisPayload> payload = job.map(obj -> payload(obj, status));
        List<AnalysisResult.Receipt> receipts = new ArrayList<>();
        for (JsonNode receipt : root.array("receipts", MAX_RECEIPTS)) {
            receipts.add(receipt(Obj.of(receipt, "result.receipts[]")));
        }
        return new AnalysisResult(status, new AnalysisResult.Delivery(deliveryState, reason), payload, receipts);
    }

    private static UntrustedAnalysisPayload payload(Obj job, AnalysisJobStatus status) {
        if (!"zoop-ai-s1-1".equals(job.string("schemaVersion", Obj.PRINTABLE))
                || !status.jobId().equals(job.string("jobId", Obj.PRINTABLE))
                || !status.inputDigest().equals(job.string("inputDigest", Obj.SHA256))
                || !status.state().wire().equals(job.string("state", Obj.PRINTABLE))) {
            throw new Malformed("result.job");
        }
        Obj input = job.object("input");
        if (!status.kind().wire().equals(input.string("kind", Obj.PRINTABLE))
                || !status.mode().wire().equals(input.string("mode", Obj.PRINTABLE))) {
            throw new Malformed("result.job.input");
        }
        return new UntrustedAnalysisPayload(status.jobId(), WireJson.compact(job.node()));
    }

    private static AnalysisResult.Receipt receipt(Obj receipt) {
        Optional<Obj> usage = receipt.optObject("usage");
        Obj config = receipt.object("config");
        return new AnalysisResult.Receipt(
                receipt.string("attemptId", Obj.PRINTABLE),
                receipt.choice("stage", AnalysisKind::fromWire),
                receipt.choice("state", AnalysisWire::callState),
                receipt.choice("mode", ExecutionMode::fromWire),
                offsetStamp(receipt, "startedAt"),
                optOffsetStamp(receipt, "receivedAt"),
                receipt.string("inputDigest", Obj.SHA256),
                usage.map(u -> new AnalysisResult.Receipt.Tokens(u.optCount("inputTokens"), u.optCount("outputTokens"),
                        u.optCount("cachedTokens"), u.optCount("reasoningTokens"))),
                receipt.optString("error", Obj.SAFE),
                Optional.ofNullable(receipt.optNumber("durationMs")),
                config.string("provider", Obj.PRINTABLE),
                config.string("providerRevision", Obj.PRINTABLE),
                config.string("model", Obj.PRINTABLE),
                config.optString("reasoningEffort", Obj.PRINTABLE),
                config.string("promptVersion", Obj.PRINTABLE),
                config.string("schemaVersion", Obj.PRINTABLE),
                config.string("policyVersion", Obj.PRINTABLE));
    }

    private static Optional<AnalysisResult.Receipt.CallState> callState(String name) {
        try {
            return Optional.of(AnalysisResult.Receipt.CallState.valueOf(name.toUpperCase(Locale.ROOT)));
        } catch (IllegalArgumentException error) {
            return Optional.empty();
        }
    }

    /** The decoded service error envelope. */
    record Rejection(String code, boolean retryable, String requestId, Optional<String> runtimeCode, Optional<String> field,
                     Optional<AnalysisJobStatus> status) {
    }

    static Rejection rejection(JsonNode node, String expectedJobId, Optional<Duration> retryAfter) {
        Obj root = Obj.of(node, "error");
        schema(root, INTERNAL_SCHEMA);
        Obj error = root.object("error");
        String requestId = error.string("requestId", REQUEST_ID);
        Optional<AnalysisJobStatus> status = Optional.empty();
        JsonNode statusNode = root.node().get("status");
        if (statusNode != null && !statusNode.isNull()) {
            if (expectedJobId == null) {
                throw new Malformed("error.status");
            }
            status = Optional.of(status(statusNode, "error.status", expectedJobId, retryAfter));
        }
        return new Rejection(error.string("code", CODE), error.bool("retryable"), requestId,
                error.optString("runtimeCode", TEXT), error.optString("field", TEXT), status);
    }
}
