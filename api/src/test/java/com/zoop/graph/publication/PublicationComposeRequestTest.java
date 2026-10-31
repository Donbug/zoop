package com.zoop.graph.publication;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;

class PublicationComposeRequestTest {
    @Test
    void bootstrapPinsActualFixtureWithoutReplacingItWithNull() {
        ObjectNode root = request(2);
        root.put("expectedActiveVersionId", "fixture-2026-10-08");
        var parsed = PublicationComposeRequest.parse(Canonical.bytes(root));
        assertNull(parsed.baseVersionId());
        assertEquals("fixture-2026-10-08", parsed.expectedActiveVersionId());
        assertEquals(2, parsed.incomingReceiptPins().size());
    }

    @Test
    void twentyIsAnIncomingCommandBoundRatherThanAStoredLineageBound() {
        assertEquals(20, PublicationComposeRequest.parse(Canonical.bytes(request(20))).incomingVersionIds().size());
        assertEquals("request_invalid", assertThrows(PublicationException.class,
                () -> PublicationComposeRequest.parse(Canonical.bytes(request(21)))).code());
    }

    @Test
    void refusesMissingPinsExtraKeysAndDuplicateKeys() {
        ObjectNode root = request(2); root.putArray("incomingReceiptPins");
        assertThrows(PublicationException.class, () -> PublicationComposeRequest.parse(Canonical.bytes(root)));
        ObjectNode suppliedPath = request(1); suppliedPath.put("artifactRoot", "/tmp/untrusted");
        assertThrows(PublicationException.class, () -> PublicationComposeRequest.parse(Canonical.bytes(suppliedPath)));
        String duplicate = Canonical.write(request(1)).replace("\"operator\":\"operator\"", "\"operator\":\"operator\",\"operator\":\"other\"");
        assertThrows(PublicationException.class, () -> PublicationComposeRequest.parse(duplicate.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    }

    private static ObjectNode request(int count) {
        ObjectNode root = StrictJson.newObject(); root.put("schemaVersion", PublicationComposeRequest.SCHEMA);
        root.putNull("baseVersionId"); root.putNull("expectedActiveVersionId"); root.putNull("expectedBaseReceiptSha256");
        var inputs = root.putArray("incomingVersionIds"); var pins = root.putArray("incomingReceiptPins");
        for (int index = 0; index < count; index++) {
            String version = "gv-" + String.format("%064x", index + 1);
            inputs.add(version); pins.addObject().put("versionId", version).put("sha256", "a".repeat(64));
        }
        root.put("expectedRuleRevision", 0); root.put("expectedReviewRevision", 0); root.put("decisionsSha256", "b".repeat(64)); root.put("operator", "operator");
        return root;
    }
}
