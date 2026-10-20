package com.zoop.graph.importer;

import java.nio.charset.StandardCharsets;
import java.util.List;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class GraphHandoffRequestParserTest {
    private static final String M = "a".repeat(64);
    private static final String B = "b".repeat(64);
    private final GraphHandoffRequestParser parser = new GraphHandoffRequestParser();

    private static byte[] json(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }

    private static String request(String handoffId, String manifest, String bundle, String operator) {
        return "{\"schemaVersion\":\"zoop-graph-handoff-import-1\",\"handoffId\":\"" + handoffId
                + "\",\"expectedManifestDigest\":\"" + manifest + "\",\"expectedBundleDigest\":\"" + bundle
                + "\",\"operator\":\"" + operator + "\"}";
    }

    private void assertInvalid(byte[] bytes) {
        assertEquals(GraphHandoffFailure.REQUEST_INVALID,
                assertThrows(GraphHandoffException.class, () -> parser.parse(bytes)).failure());
    }

    @Test
    void aClosedRequestWithBothPinsAndAnOperatorIsParsed() {
        GraphHandoffRequest parsed = parser.parse(json(request("handoff-1.a:b_c", M, B, "alice.kim")));

        assertEquals(new GraphHandoffRequest("handoff-1.a:b_c", M, B, "alice.kim"), parsed);
    }

    @Test
    void anythingElseIsRequestInvalid() {
        String valid = request("handoff-1", M, B, "alice");
        assertInvalid(new byte[0]);
        assertInvalid(json("[]"));
        assertInvalid(json("{}"));
        assertInvalid(json(valid.replace("\"operator\":\"alice\"", "\"operator\":\"alice\",\"activate\":true")));
        assertInvalid(json(valid.replace("\"expectedBundleDigest\":\"" + B + "\",", "")));
        assertInvalid(json(valid.replace("zoop-graph-handoff-import-1", "zoop-graph-handoff-import-2")));
        assertInvalid(json(request("handoff-1", M.toUpperCase(), B, "alice")));
        assertInvalid(json(request("handoff-1", "short", B, "alice")));
        assertInvalid(json(request("한글", M, B, "alice")));
        assertInvalid(json(request("x".repeat(201), M, B, "alice")));
        assertInvalid(json(request("handoff-1", M, B, "operator:with-colon")));
        assertInvalid(json(request("handoff-1", M, B, "")));
        assertInvalid(json("{\"schemaVersion\":\"zoop-graph-handoff-import-1\",\"schemaVersion\":\"zoop-graph-handoff-import-1\"}"));
        assertInvalid(json(valid + valid));
        assertInvalid(new byte[GraphHandoffRequestParser.MAX_BYTES + 1]);
    }

    @Test
    void thereIsNoKeyThatCouldCarryABundleAPathOrAnActivation() {
        for (String key : List.of("bundle", "manifest", "path", "activate", "publish", "graphVersion", "grant")) {
            assertInvalid(json(request("handoff-1", M, B, "alice").replace("\"operator\"", "\"" + key + "\":\"x\",\"operator\"")));
        }
    }
}
