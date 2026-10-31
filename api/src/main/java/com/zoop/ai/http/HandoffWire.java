package com.zoop.ai.http;

import java.util.LinkedHashSet;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

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

    /**
     * {@code HdErrorEnvelope}: {@code error} with {@code code}, {@code retryable} and the echoed {@code requestId}; {@code runtimeCode}
     * and {@code field} may be absent (the contract does not require them), and nothing else is allowed.
     */
    static AiHttpTransport.Rejections rejections() {
        return (document, status, retryAfter, operation, requestId) -> {
            if (document == null || !document.isObject() || !document.has("error")
                    || !Set.of("schemaVersion", "error").containsAll(names(document))) {
                throw new Malformed("error");
            }
            if (document.has("schemaVersion") && !ENVELOPE_SCHEMA.equals(document.get("schemaVersion").stringValue())) {
                throw new Malformed("error.schemaVersion");
            }
            JsonNode error = document.get("error");
            if (!error.isObject() || !Set.of("code", "retryable", "requestId", "runtimeCode", "field").containsAll(names(error))) {
                throw new Malformed("error");
            }
            WireJson.Obj body = WireJson.Obj.of(error, "error");
            if (!body.string("requestId", AnalysisWire.REQUEST_ID).equals(requestId)) throw new Malformed("error.requestId");
            return new HandoffServiceErrorException(operation, requestId, status, body.string("code", AnalysisWire.CODE),
                    body.bool("retryable"), optional(body, error, "runtimeCode"), optional(body, error, "field"), retryAfter);
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
