package com.zoop.ai.http;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.HandoffServiceErrorException;
import com.zoop.ai.handoff.HandoffExposureClient;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@code POST /internal/v1/graph-handoffs/exposure} over the shared bounded transport (no proxy, redirect or retry). The query is
 * read-only (no idempotency key, job or cache on the AI side) and its answer is the {@code HdExposure} envelope; only the envelope
 * is checked here, the report inside is the caller's to validate.
 */
public final class HttpHandoffExposureClient implements HandoffExposureClient, AutoCloseable {
    static final String PATH = "/internal/v1/graph-handoffs/exposure";
    static final String QUERY_SCHEMA = "zoop-handoff-exposure-1";
    static final String ENVELOPE_SCHEMA = "zoop-ai-internal-handoff-1";
    /** The contract's request limit (declared and received length). */
    static final int MAX_REQUEST_BYTES = 65_536;
    private static final Pattern HANDOFF_ID = Pattern.compile("[A-Za-z0-9._:-]{1,200}");
    private final AiHttpTransport transport;

    public HttpHandoffExposureClient(AiClientSettings settings) {
        transport = new AiHttpTransport(settings);
    }

    @Override
    public JsonNode exposure(List<String> handoffIds, JsonNode changed) {
        Objects.requireNonNull(changed, "changed");
        Set<String> ids = new LinkedHashSet<>(handoffIds);
        if (ids.isEmpty() || ids.size() > MAX_HANDOFFS || ids.size() != handoffIds.size()
                || ids.stream().anyMatch(id -> !HANDOFF_ID.matcher(id).matches()) || !changed.isObject()) {
            throw new IllegalArgumentException("exposure query");
        }
        ObjectNode query = StrictJson.newObject();
        query.put("schemaVersion", QUERY_SCHEMA);
        ArrayNode list = query.putArray("handoffIds");
        handoffIds.forEach(list::add);
        query.set("changed", changed);
        byte[] body = StrictJson.write(query);
        if (body.length > MAX_REQUEST_BYTES) throw new IllegalArgumentException("exposure query size");
        var reply = transport.exchange(AiOperation.EXPOSURE, "POST", transport.uri(PATH), body, null, rejections(), 200);
        return AiHttpTransport.decode(reply, () -> report(reply.body()));
    }

    /** The {@code HdExposure} envelope: {@code report} and, when present, the handoff envelope schema; nothing else. */
    static JsonNode report(JsonNode document) {
        if (document == null || !document.isObject()) throw new Malformed("exposure");
        Set<String> keys = new LinkedHashSet<>();
        document.properties().forEach(entry -> keys.add(entry.getKey()));
        if (!keys.contains("report") || !Set.of("schemaVersion", "report").containsAll(keys)) throw new Malformed("exposure");
        if (keys.contains("schemaVersion")) {
            JsonNode schema = document.get("schemaVersion");
            if (!schema.isString() || !ENVELOPE_SCHEMA.equals(schema.stringValue())) throw new Malformed("exposure.schemaVersion");
        }
        JsonNode report = document.get("report");
        if (!report.isObject()) throw new Malformed("exposure.report");
        return report;
    }

    @Override
    public void close() {
        transport.close();
    }

    /**
     * {@code HdErrorEnvelope}: {@code error} with {@code code}, {@code retryable} and the echoed {@code requestId}; {@code runtimeCode}
     * and {@code field} may be absent (the contract does not require them), and nothing else is allowed.
     */
    private static AiHttpTransport.Rejections rejections() {
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

    private static Set<String> names(JsonNode object) {
        Set<String> names = new LinkedHashSet<>();
        object.properties().forEach(entry -> names.add(entry.getKey()));
        return names;
    }

    private static java.util.Optional<String> optional(WireJson.Obj body, JsonNode error, String name) {
        return error.has(name) ? body.optString(name, AnalysisWire.TEXT) : java.util.Optional.empty();
    }
}
