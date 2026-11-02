package com.zoop.ai.http;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.http.AiHttpTransport.Reply;
import com.zoop.ai.http.WireJson.Malformed;
import com.zoop.ai.observation.ObservationExportClient;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@code POST /internal/v1/observations/export} over the shared bounded transport (no proxy, redirect or retry). The body is the
 * closed S2-1 selector; the 200 answer is returned as the service sent it, byte for byte, because the strict S2-1 parser
 * ({@code IngestionExportParser}) verifies the export from those bytes exactly as it verifies the CLI's stdout. Only the
 * envelope is checked here: one JSON object with the export schema whose {@code observation} echoes the selector. The route is
 * read-only (no idempotency key), bounded on the AI side by a 45 s child deadline, a 16 MiB answer and two concurrent exports,
 * so the request deadline must exceed 45 s and the response bound must be at least 16 MiB.
 */
public final class HttpObservationExportClient implements ObservationExportClient, AutoCloseable {
    static final String PATH = "/internal/v1/observations/export";
    private final AiHttpTransport transport;

    public HttpObservationExportClient(AiClientSettings settings) {
        transport = new AiHttpTransport(settings);
    }

    @Override
    public byte[] export(Selector selector) {
        byte[] body = selectorJson(selector);
        Reply reply = transport.exchange(AiOperation.OBSERVATION_EXPORT, "POST", transport.uri(PATH), body, null,
                ObservationWire.rejections(), 200);
        return AiHttpTransport.decode(reply, () -> {
            requireEnvelope(reply.body(), selector);
            return reply.raw();
        });
    }

    /** The CLI's stdin selector, the same bytes {@code ProcessIngestionExporter} writes. */
    static byte[] selectorJson(Selector selector) {
        ObjectNode body = StrictJson.newObject();
        body.put("schemaVersion", ObservationWire.EXPORT_SCHEMA);
        body.put("roundId", selector.roundId());
        body.put("sourceId", selector.sourceId());
        body.put("page", selector.page());
        body.put("ordinal", selector.ordinal());
        body.put("documentId", selector.documentId());
        body.put("rawVersion", selector.rawVersion());
        body.put("documentVersion", selector.documentVersion());
        return StrictJson.write(body);
    }

    /** The answer is an export document (schema, {@code observation} object) for this very selector; the parser checks the rest. */
    static void requireEnvelope(JsonNode document, Selector selector) {
        if (document == null || !document.isObject()) throw new Malformed("export");
        JsonNode schema = document.get("schemaVersion");
        if (schema == null || !schema.isString() || !ObservationWire.EXPORT_SCHEMA.equals(schema.stringValue())) {
            throw new Malformed("export.schemaVersion");
        }
        JsonNode observation = document.get("observation");
        if (observation == null || !observation.isObject()) throw new Malformed("export.observation");
        if (!text(observation, "roundId").equals(selector.roundId()) || !text(observation, "sourceId").equals(selector.sourceId())
                || !text(observation, "documentId").equals(selector.documentId())
                || !text(observation, "rawVersion").equals(selector.rawVersion())
                || !text(observation, "documentVersion").equals(selector.documentVersion())
                || !number(observation, "page", selector.page()) || !number(observation, "ordinal", selector.ordinal())) {
            throw new Malformed("export.observation");
        }
    }

    private static String text(JsonNode object, String name) {
        JsonNode value = object.get(name);
        if (value == null || !value.isString()) throw new Malformed("export.observation." + name);
        return value.stringValue();
    }

    private static boolean number(JsonNode object, String name, int expected) {
        JsonNode value = object.get(name);
        return value != null && value.isIntegralNumber() && value.canConvertToInt() && value.intValue() == expected;
    }

    @Override
    public void close() {
        transport.close();
    }
}
