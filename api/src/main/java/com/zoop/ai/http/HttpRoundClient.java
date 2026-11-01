package com.zoop.ai.http;

import java.net.URI;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.http.AiHttpTransport.Reply;
import com.zoop.ai.round.RoundHandoffClient;
import com.zoop.ai.round.RoundRunClient;
import com.zoop.common.json.StrictJson;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * {@code /internal/v1/round-runs} and {@code /internal/v1/round-handoffs} over the shared bounded transport (no proxy, redirect
 * or retry). Both POSTs are accepted with 202 and carry the round id as their idempotency key, so a repeated request after a
 * lost answer is the same run or freeze; a 200 is accepted too, for a service that answers the current status at once. The
 * reads are plain GETs. Only the status documents are decoded here; the handoff a ready freeze names is the importer's to read
 * and verify through the handoff-read client.
 */
public final class HttpRoundClient implements RoundRunClient, RoundHandoffClient, AutoCloseable {
    static final String RUNS = "/internal/v1/round-runs";
    static final String HANDOFFS = "/internal/v1/round-handoffs";
    private final AiHttpTransport transport;

    public HttpRoundClient(AiClientSettings settings) {
        transport = new AiHttpTransport(settings);
    }

    @Override
    public RoundRun request(String roundId) {
        ObjectNode body = StrictJson.newObject();
        body.put("schemaVersion", RoundWire.RUN_SCHEMA);
        body.put("roundId", checked(roundId));
        Reply reply = transport.exchange(AiOperation.ROUND_RUN, "POST", transport.uri(RUNS), StrictJson.write(body), roundId,
                RoundWire.rejections(), 202, 200);
        return AiHttpTransport.decode(reply, () -> RoundWire.run(reply.body(), roundId));
    }

    @Override
    public RoundRun runStatus(String roundId) {
        Reply reply = transport.exchange(AiOperation.ROUND_READ, "GET", uri(RUNS, roundId), null, null, RoundWire.rejections(), 200);
        return AiHttpTransport.decode(reply, () -> RoundWire.run(reply.body(), roundId));
    }

    @Override
    public RoundHandoff request(Request request) {
        ObjectNode body = StrictJson.newObject();
        body.put("schemaVersion", RoundWire.HANDOFF_SCHEMA);
        body.put("roundId", checked(request.roundId()));
        request.ingestionRoundId().ifPresent(id -> body.put("ingestionRoundId", id));
        request.planId().ifPresent(id -> body.put("planId", id));
        body.set("bindings", bindings(request.bindings()));
        Reply reply = transport.exchange(AiOperation.ROUND_HANDOFF, "POST", transport.uri(HANDOFFS), StrictJson.write(body),
                request.roundId(), RoundWire.rejections(), 202, 200);
        return AiHttpTransport.decode(reply, () -> RoundWire.handoff(reply.body(), request.roundId()));
    }

    @Override
    public RoundHandoff handoffStatus(String roundId) {
        Reply reply = transport.exchange(AiOperation.ROUND_READ, "GET", uri(HANDOFFS, roundId), null, null,
                RoundWire.rejections(), 200);
        return AiHttpTransport.decode(reply, () -> RoundWire.handoff(reply.body(), roundId));
    }

    /** The bindings export is one JSON object ({@code zoop-app-document-bindings-1}); it travels embedded, not re-encoded as text. */
    static JsonNode bindings(byte[] exported) {
        try {
            JsonNode node = StrictJson.parseObject(exported).node();
            if (!node.isObject()) throw new IllegalArgumentException("bindings");
            return node;
        } catch (StrictJson.Malformed malformed) {
            throw new IllegalArgumentException("bindings", malformed);
        }
    }

    private URI uri(String family, String roundId) {
        return transport.uri(family + "/" + AiHttpTransport.segment(checked(roundId)));
    }

    private static String checked(String roundId) {
        if (roundId == null || !RoundWire.ROUND_ID.matcher(roundId).matches()) {
            throw new IllegalArgumentException("roundId");
        }
        return roundId;
    }

    @Override
    public void close() {
        transport.close();
    }

}
