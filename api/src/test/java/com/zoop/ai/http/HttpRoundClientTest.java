package com.zoop.ai.http;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Optional;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.RoundServiceErrorException;
import com.zoop.ai.round.RoundHandoffClient;
import com.zoop.ai.round.RoundHandoffClient.RoundHandoff;
import com.zoop.ai.round.RoundRunClient.RoundRun;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class HttpRoundClientTest {
    private static final String ROUND = "round-20261030T0905";
    private static final String INGESTION = "slot-" + "1".repeat(64);
    private static final String PLAN = "s2plan-" + "2".repeat(64);
    private static final String DIGEST = "3".repeat(64);
    private static final String HANDOFF = "hr-" + "4".repeat(64);
    private static final byte[] BINDINGS = "{\"schemaVersion\":\"zoop-app-document-bindings-1\",\"bindings\":[]}".getBytes(StandardCharsets.UTF_8);
    private StubAiServer server;
    private HttpRoundClient client;

    @BeforeEach
    void start() throws IOException {
        server = new StubAiServer();
        client = new HttpRoundClient(AiClientSettings.of(server.baseUrl(), StubAiServer.TOKEN, Duration.ofSeconds(1),
                Duration.ofSeconds(2), 1 << 20));
    }

    @AfterEach
    void stop() {
        client.close();
        server.close();
    }

    private static String run(String state, String extra) {
        return "{\"schemaVersion\":\"zoop-ai-round-run-1\",\"roundId\":\"" + ROUND + "\",\"state\":\"" + state + "\"" + extra + "}";
    }

    private static String handoff(String state, String extra) {
        return "{\"schemaVersion\":\"zoop-ai-round-handoff-1\",\"roundId\":\"" + ROUND + "\",\"state\":\"" + state + "\"" + extra + "}";
    }

    @Test
    void aRunRequestIsAPostKeyedOnTheRoundIdAndAcceptedWithTwoOhTwo() throws Exception {
        server.respond(StubAiServer.Reply.json(202, run("running", "")));

        RoundRun accepted = client.request(ROUND);

        assertEquals(RoundRun.State.RUNNING, accepted.state());
        assertTrue(accepted.planId().isEmpty());
        var seen = server.requests.getFirst();
        assertEquals("POST", seen.method());
        assertEquals(HttpRoundClient.RUNS, seen.path());
        assertEquals(ROUND, seen.header("Idempotency-Key"));
        var body = JsonMapper.builder().build().readTree(seen.body());
        assertEquals("zoop-ai-round-run-1", body.get("schemaVersion").stringValue());
        assertEquals(ROUND, body.get("roundId").stringValue());
        assertEquals(2, body.size());
    }

    @Test
    void aReadyRunCarriesTheIngestionRoundAndThePlanAndNoNewMaterialCarriesACode() {
        server.respond(StubAiServer.Reply.json(200, run("ready", ",\"ingestionRoundId\":\"" + INGESTION + "\",\"planId\":\"" + PLAN
                + "\",\"planDigest\":\"" + DIGEST + "\",\"observedAt\":\"2026-10-30T00:06:00Z\"")));
        RoundRun ready = client.runStatus(ROUND);
        assertEquals(RoundRun.State.READY, ready.state());
        assertEquals(Optional.of(INGESTION), ready.ingestionRoundId());
        assertEquals(Optional.of(PLAN), ready.planId());
        assertEquals(Optional.of(DIGEST), ready.planDigest());
        assertEquals("GET", server.requests.getFirst().method());
        assertEquals(HttpRoundClient.RUNS + "/" + ROUND, server.requests.getFirst().path());

        server.respond(StubAiServer.Reply.json(200, run("no_new_material", ",\"code\":\"outside_operating_window\",\"ingestionRoundId\":null")));
        RoundRun none = client.runStatus(ROUND);
        assertEquals(RoundRun.State.NO_NEW_MATERIAL, none.state());
        assertEquals(Optional.of("outside_operating_window"), none.code());
        assertTrue(none.ingestionRoundId().isEmpty());

        server.respond(StubAiServer.Reply.json(200, run("failed", ",\"code\":\"tick_failed\"")));
        assertEquals(Optional.of("tick_failed"), client.runStatus(ROUND).code());
    }

    @Test
    void aRunDocumentIsRefusedWhenItBreaksTheContract() {
        for (String bad : new String[] {
                run("ready", ",\"ingestionRoundId\":\"" + INGESTION + "\""),                      // ready without a plan
                run("running", ",\"planId\":\"" + PLAN + "\",\"planDigest\":\"" + DIGEST + "\""), // a plan before ready
                run("ready", ",\"ingestionRoundId\":\"" + INGESTION + "\",\"planId\":\"" + PLAN + "\""), // digest missing
                run("failed", ""),                                                                 // failed without a code
                run("paused", ""),                                                                 // unknown state
                run("running", ",\"extra\":1"),                                                    // foreign key
                "{\"schemaVersion\":\"zoop-ai-round-run-1\",\"roundId\":\"round-20261030T0935\",\"state\":\"running\"}"}) {
            server.respond(StubAiServer.Reply.json(200, bad));
            assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED,
                    assertThrows(AiTransportException.class, () -> client.runStatus(ROUND)).failure(), bad);
        }
    }

    @Test
    void aFreezeRequestEmbedsTheBindingsAndTheOptionalPlanAndIngestionRound() throws Exception {
        server.respond(StubAiServer.Reply.json(202, handoff("running", "")));

        client.request(new RoundHandoffClient.Request(ROUND, Optional.of(INGESTION), Optional.of(PLAN), BINDINGS));

        var seen = server.requests.getFirst();
        assertEquals(HttpRoundClient.HANDOFFS, seen.path());
        assertEquals(ROUND, seen.header("Idempotency-Key"));
        var body = JsonMapper.builder().build().readTree(seen.body());
        assertEquals("zoop-ai-round-handoff-1", body.get("schemaVersion").stringValue());
        assertEquals(INGESTION, body.get("ingestionRoundId").stringValue());
        assertEquals(PLAN, body.get("planId").stringValue());
        assertEquals("zoop-app-document-bindings-1", body.get("bindings").get("schemaVersion").stringValue());
        assertTrue(body.get("bindings").get("bindings").isArray());

        server.respond(StubAiServer.Reply.json(202, handoff("running", "")));
        client.request(new RoundHandoffClient.Request(ROUND, Optional.empty(), Optional.empty(), BINDINGS));
        var carryOnly = JsonMapper.builder().build().readTree(server.requests.get(1).body());
        assertFalse(carryOnly.has("planId"), "a carry-only freeze names no plan");
        assertFalse(carryOnly.has("ingestionRoundId"));
    }

    @Test
    void aReadyHandoffCarriesTheIdDigestsAndSelectionAndTheOtherStatesCarryACode() {
        server.respond(StubAiServer.Reply.json(200, handoff("ready", ",\"handoffId\":\"" + HANDOFF + "\",\"manifestDigest\":\"" + DIGEST
                + "\",\"bundleDigest\":\"" + DIGEST + "\",\"selection\":{\"schemaVersion\":\"zoop-ai-handoff-selection-1\",\"jobs\":[]}")));
        RoundHandoff ready = client.handoffStatus(ROUND);
        assertEquals(RoundHandoff.State.READY, ready.state());
        assertEquals(Optional.of(HANDOFF), ready.handoffId());
        assertEquals(Optional.of(DIGEST), ready.manifestDigest());
        assertEquals("zoop-ai-handoff-selection-1", ready.selection().orElseThrow().get("schemaVersion").stringValue());

        server.respond(StubAiServer.Reply.json(200, handoff("analysis_incomplete", ",\"code\":\"analysis_incomplete\"")));
        assertEquals(RoundHandoff.State.ANALYSIS_INCOMPLETE, client.handoffStatus(ROUND).state());
        server.respond(StubAiServer.Reply.json(200, handoff("no_public_material", ",\"code\":\"window_empty\"")));
        RoundHandoff empty = client.handoffStatus(ROUND);
        assertEquals(RoundHandoff.State.NO_PUBLIC_MATERIAL, empty.state());
        assertEquals(Optional.of("window_empty"), empty.code());

        for (String bad : new String[] {
                handoff("ready", ",\"handoffId\":\"" + HANDOFF + "\""),                        // ready without digests
                handoff("running", ",\"handoffId\":\"" + HANDOFF + "\""),                      // an id before ready
                handoff("failed", ""),                                                         // failed without a code
                handoff("ready", ",\"handoffId\":\"" + HANDOFF + "\",\"manifestDigest\":\"" + DIGEST + "\",\"bundleDigest\":\""
                        + DIGEST + "\",\"selection\":[1]")}) {                                 // selection must be an object
            server.respond(StubAiServer.Reply.json(200, bad));
            assertEquals(AiTransportException.Failure.RESPONSE_MALFORMED,
                    assertThrows(AiTransportException.class, () -> client.handoffStatus(ROUND)).failure(), bad);
        }
    }

    @Test
    void aRefusalEnvelopeBecomesTheRoundFamilysExceptionAndAMutatingFiveHundredMayHaveBeenProcessed() {
        server.respond(seen -> StubAiServer.Reply.json(409, StubAiServer.error("round_busy", true, seen.requestId(), null, null))
                .header("Retry-After", "5"));
        RoundServiceErrorException busy = assertThrows(RoundServiceErrorException.class, () -> client.request(ROUND));
        assertEquals(409, busy.httpStatus());
        assertEquals("round_busy", busy.code());
        assertEquals(AiOperation.ROUND_RUN, busy.operation());
        assertEquals(Duration.ofSeconds(5), busy.retryAfter().orElseThrow());
        assertFalse(busy.requestMaybeProcessed(), "a 4xx says the request was not taken");

        server.respond(seen -> StubAiServer.Reply.json(503, StubAiServer.error("runtime_unavailable", true, seen.requestId(), null, null)));
        RoundServiceErrorException down = assertThrows(RoundServiceErrorException.class, () -> client.request(ROUND));
        assertTrue(down.requestMaybeProcessed(), "a 5xx after a POST may still have started the run");

        server.respond(seen -> StubAiServer.Reply.json(404, StubAiServer.error("round_not_found", false, seen.requestId(), null, null)));
        assertEquals(AiOperation.ROUND_READ, assertThrows(RoundServiceErrorException.class, () -> client.runStatus(ROUND)).operation());
    }

    @Test
    void theRoundIdAndTheBindingsAreCheckedBeforeAnyRequest() {
        assertThrows(IllegalArgumentException.class, () -> client.request("round-1"));
        assertThrows(IllegalArgumentException.class, () -> client.handoffStatus("../x"));
        assertThrows(IllegalArgumentException.class, () -> client.request(new RoundHandoffClient.Request(ROUND, Optional.empty(),
                Optional.empty(), "[1]".getBytes(StandardCharsets.UTF_8))));
        assertTrue(server.requests.isEmpty());
    }
}
