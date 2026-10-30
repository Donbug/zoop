package com.zoop.ai.http;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
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
    static final String ENVELOPE_SCHEMA = HandoffWire.ENVELOPE_SCHEMA;
    /** The contract's request limit (declared and received length). */
    static final int MAX_REQUEST_BYTES = 65_536;
    private final AiHttpTransport transport;

    public HttpHandoffExposureClient(AiClientSettings settings) {
        transport = new AiHttpTransport(settings);
    }

    @Override
    public JsonNode exposure(List<String> handoffIds, JsonNode changed) {
        Objects.requireNonNull(changed, "changed");
        Set<String> ids = new LinkedHashSet<>(handoffIds);
        if (ids.isEmpty() || ids.size() > MAX_HANDOFFS || ids.size() != handoffIds.size()
                || ids.stream().anyMatch(id -> !HandoffWire.HANDOFF_ID.matcher(id).matches()) || !changed.isObject()) {
            throw new IllegalArgumentException("exposure query");
        }
        ObjectNode query = StrictJson.newObject();
        query.put("schemaVersion", QUERY_SCHEMA);
        ArrayNode list = query.putArray("handoffIds");
        handoffIds.forEach(list::add);
        query.set("changed", changed);
        byte[] body = StrictJson.write(query);
        if (body.length > MAX_REQUEST_BYTES) throw new IllegalArgumentException("exposure query size");
        var reply = transport.exchange(AiOperation.EXPOSURE, "POST", transport.uri(PATH), body, null, HandoffWire.rejections(), 200);
        return AiHttpTransport.decode(reply, () -> report(reply.body()));
    }

    /** The {@code HdExposure} envelope: {@code report} and, when present, the handoff envelope schema; nothing else. */
    static JsonNode report(JsonNode document) {
        if (document == null || !document.isObject()) throw new Malformed("exposure");
        Set<String> keys = HandoffWire.names(document);
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
}
