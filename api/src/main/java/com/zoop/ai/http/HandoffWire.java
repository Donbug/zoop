package com.zoop.ai.http;

import java.util.LinkedHashSet;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

import java.time.Duration;

import com.zoop.ai.AiOperation;
import com.zoop.ai.AiServiceRejectionException;
import com.zoop.ai.HandoffServiceErrorException;
import com.zoop.ai.http.WireJson.Malformed;
import tools.jackson.databind.JsonNode;

/**
 * The pieces every client of the handoff family shares: the envelope schema, the handoff id alphabet, the delivery reason
 * alphabet and the {@code HdErrorEnvelope} decoder.
 */
public final class HandoffWire {
    public static final String ENVELOPE_SCHEMA = "zoop-ai-internal-handoff-1";
    /** The contract's handoff id ({@code HANDOFF_ID_PATTERN} on the AI side): the operator request and every route share it. */
    public static final Pattern HANDOFF_ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    /**
     * A withheld answer's {@code delivery.reason}: the service's own {@code Safe} alphabet, wider than the error-code alphabet,
     * because reason codes are the producer's and new ones may arrive (the contract says never to fail on an unknown reason).
     */
    static final Pattern REASON = Pattern.compile("[A-Za-z0-9_.:-]{1,80}");

    private HandoffWire() {
    }

    /** The typed exception of one family, built from a decoded envelope. */
    @FunctionalInterface
    interface EnvelopeException {
        AiServiceRejectionException create(AiOperation operation, String requestId, int status, String code, boolean retryable,
                                           Optional<String> runtimeCode, Optional<String> field, Optional<Duration> retryAfter);
    }

    /**
     * {@code HdErrorEnvelope}: {@code error} with {@code code}, {@code retryable} and the echoed {@code requestId}; {@code runtimeCode}
     * and {@code field} may be absent (the contract does not require them), and nothing else is allowed.
     */
    static AiHttpTransport.Rejections rejections() {
        return envelope(ENVELOPE_SCHEMA, Set.of("schemaVersion", "error"), HandoffServiceErrorException::new);
    }

    /**
     * The error envelope every read-only family shares: {@code error} with {@code code}, {@code retryable} and the echoed
     * {@code requestId}, {@code runtimeCode} and {@code field} absent or null; {@code schemaVersion}, when present, is the family's
     * constant; any other top-level key allowed by {@code topKeys} must be null (a job status this family never has).
     */
    static AiHttpTransport.Rejections envelope(String schema, Set<String> topKeys, EnvelopeException exception) {
        return (document, status, retryAfter, operation, requestId) -> {
            if (document == null || !document.isObject() || !document.has("error") || !topKeys.containsAll(names(document))) {
                throw new Malformed("error");
            }
            JsonNode declared = document.get("schemaVersion");
            if (declared != null && (!declared.isString() || !schema.equals(declared.stringValue()))) {
                throw new Malformed("error.schemaVersion");
            }
            for (String name : names(document)) {
                if (!name.equals("schemaVersion") && !name.equals("error") && !document.get(name).isNull()) throw new Malformed("error." + name);
            }
            JsonNode error = document.get("error");
            if (!error.isObject() || !Set.of("code", "retryable", "requestId", "runtimeCode", "field").containsAll(names(error))) {
                throw new Malformed("error");
            }
            WireJson.Obj body = WireJson.Obj.of(error, "error");
            if (!body.string("requestId", AnalysisWire.REQUEST_ID).equals(requestId)) throw new Malformed("error.requestId");
            return exception.create(operation, requestId, status, body.string("code", AnalysisWire.CODE), body.bool("retryable"),
                    optional(body, error, "runtimeCode"), optional(body, error, "field"), retryAfter);
        };
    }

    static Set<String> names(JsonNode object) {
        Set<String> names = new LinkedHashSet<>();
        object.properties().forEach(entry -> names.add(entry.getKey()));
        return names;
    }

    private static Optional<String> optional(WireJson.Obj body, JsonNode error, String name) {
        return error.has(name) ? body.optString(name, AnalysisWire.TEXT) : Optional.empty();
    }
}
