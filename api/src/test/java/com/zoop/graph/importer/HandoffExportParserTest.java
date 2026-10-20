package com.zoop.graph.importer;

import java.util.function.Consumer;

import com.zoop.common.json.Canonical;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** The envelope the installed CLI prints, checked against the pins of the request, in the documented order. */
class HandoffExportParserTest {
    private final HandoffExportParser parser = new HandoffExportParser();
    private final HandoffFixtures.Built built = HandoffFixtures.build();

    private GraphHandoffFailure failure(byte[] export, GraphHandoffRequest request) {
        return assertThrows(GraphHandoffException.class, () -> parser.parse(export, request)).failure();
    }

    /** The request that pins the envelope as it is NOW (after a change), so only the content can fail. */
    private static GraphHandoffRequest pinning(byte[] export) {
        JsonNode root = HandoffFixtures.parse(export);
        return new GraphHandoffRequest(root.get("handoffId").stringValue(), Canonical.digest(root.get("manifest")),
                Canonical.sha256(Canonical.bytes(root.get("bundle"))), "operator-a");
    }

    private void assertInvalidEnvelope(String what, Consumer<ObjectNode> change) {
        byte[] changed = HandoffFixtures.envelopeAfter(built, change);
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, failure(changed, pinning(changed)), what);
    }

    @Test
    void aCurrentEnvelopeIsAcceptedAndItsDigestsAreRecomputedFromTheCanonicalJson() {
        VerifiedHandoff verified = parser.parse(built.envelopeBytes(), built.request());

        assertEquals(built.manifestDigest(), verified.manifestDigest());
        assertEquals(built.bundleDigest(), verified.bundleDigest());
        assertEquals(HandoffFixtures.HANDOFF_ID, verified.bundle().handoffId());
        assertEquals(1, verified.bundle().sources().size());
        assertEquals(verified.manifest().sources(), verified.bundle().sources());
        assertEquals(1, verified.attemptsNode().size());
    }

    @Test
    void theRequestPinsDecideBeforeAnythingElseIsRead() {
        for (GraphHandoffRequest request : new GraphHandoffRequest[] {
                new GraphHandoffRequest(built.request().handoffId(), "0".repeat(64), built.bundleDigest(), "operator-a"),
                new GraphHandoffRequest(built.request().handoffId(), built.manifestDigest(), "0".repeat(64), "operator-a")}) {
            // An invalid bundle behind a wrong pin is still reported as the pin mismatch: nothing else was read.
            byte[] invalid = HandoffFixtures.envelopeAfter(built, e -> ((ObjectNode) e.get("bundle")).put("junk", 1));

            assertEquals(GraphHandoffFailure.PIN_MISMATCH, failure(built.envelopeBytes(), request));
            assertEquals(GraphHandoffFailure.PIN_MISMATCH, failure(invalid, request));
        }
    }

    @Test
    void theEnvelopeMustBeExactlyWhatTheCliPrintsForACurrentDelivery() {
        assertInvalidEnvelope("unknown key", e -> e.put("operatorPath", "/private/x"));
        assertInvalidEnvelope("missing key", e -> e.remove("attempts"));
        assertInvalidEnvelope("state", e -> e.put("state", "reserved"));
        assertInvalidEnvelope("publication", e -> e.put("publication", "published"));
        assertInvalidEnvelope("next", e -> e.put("next", "recover"));
        assertInvalidEnvelope("failure", e -> e.putObject("failure").put("code", "x"));
        assertInvalidEnvelope("model calls", e -> ((ObjectNode) e.get("usage")).put("modelCalls", 1));
        assertInvalidEnvelope("delivery status", e -> ((ObjectNode) e.get("delivery")).put("status", "withheld"));
        assertInvalidEnvelope("delivery key", e -> ((ObjectNode) e.get("delivery")).put("extra", true));
        assertInvalidEnvelope("delivery checks", e -> ((ObjectNode) e.get("delivery")).putArray("checks").add("x"));
        assertInvalidEnvelope("attempt kind", e -> ((ObjectNode) e.get("attempts").get(0)).put("kind", "export"));
        assertInvalidEnvelope("schema", e -> e.put("schemaVersion", "zoop-ai-handoff-2"));
    }

    @Test
    void theProducersReceiptMustAgreeWithWhatWasRecomputed() {
        assertInvalidEnvelope("bundle size", e -> ((ObjectNode) e.get("receipt")).put("bundleBytes", 1));
        assertInvalidEnvelope("bundle digest", e -> ((ObjectNode) e.get("receipt")).put("bundleDigest", "0".repeat(64)));
        assertInvalidEnvelope("manifest digest", e -> ((ObjectNode) e.get("receipt")).put("manifestDigest", "0".repeat(64)));
        assertInvalidEnvelope("content digest", e -> ((ObjectNode) e.get("receipt")).put("contentDigest", "0".repeat(64)));
        assertInvalidEnvelope("receipt counts", e -> ((ObjectNode) e.get("receipt").get("counts")).put("evidence", 99));
        assertInvalidEnvelope("receipt provenance", e -> ((ObjectNode) e.get("receipt").get("provenance")).put("recordingKind", "x"));
        assertInvalidEnvelope("receipt sources", e -> ((ObjectNode) e.get("receipt").get("sources").get(0)).put("reviewDigest", "0".repeat(64)));
        assertInvalidEnvelope("receipt files", e -> ((ObjectNode) e.get("receipt").get("files")).put("bindings", "0".repeat(64)));
        assertInvalidEnvelope("receipt handoff id", e -> ((ObjectNode) e.get("receipt")).put("handoffId", "other"));
    }

    @Test
    void theManifestAndTheBundleMustAgreeOnIdentityAndPins() {
        assertInvalidEnvelope("manifest handoff id", e -> ((ObjectNode) e.get("manifest")).put("handoffId", "other"));
        assertInvalidEnvelope("manifest source kind", e -> ((ObjectNode) e.get("manifest")).put("sourceKind", "actual"));
        assertInvalidEnvelope("manifest file pin", e -> ((ObjectNode) e.get("manifest").get("files")).put("canonical", "0".repeat(64)));
        assertInvalidEnvelope("manifest source pin", e -> ((ObjectNode) e.get("manifest").get("sources").get(0)).put("reviewDigest", "0".repeat(64)));
        assertInvalidEnvelope("manifest unknown field", e -> ((ObjectNode) e.get("manifest")).put("operatorPath", "/private/x"));
        assertInvalidEnvelope("manifest policy", e -> ((ObjectNode) e.get("manifest")).put("policyVersion", "zoop-public-projection-policy-2"));
    }

    @Test
    void aBundleThatBreaksTheClosedSchemaIsABundleFailureWhenItsPinsMatch() {
        byte[] broken = HandoffFixtures.envelopeAfter(built, e -> ((ObjectNode) e.get("bundle")).put("junk", 1));

        assertEquals(GraphHandoffFailure.BUNDLE_INVALID, failure(broken, pinning(broken)));
    }

    @Test
    void aMovedReviewStateIsRefusedEvenThoughTheContentIsUnchanged() {
        byte[] moved = HandoffFixtures.envelopeAfter(built, e -> ((ObjectNode) e.get("delivery")).put("reviewDigestMatches", false));

        assertEquals(GraphHandoffFailure.REVIEW_STATE_CHANGED, failure(moved, built.request()));
    }

    @Test
    void theHandoffIdOfTheRequestMustBeTheEnvelopes() {
        GraphHandoffRequest other = new GraphHandoffRequest("another-handoff", built.manifestDigest(), built.bundleDigest(), "operator-a");

        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, failure(built.envelopeBytes(), other));
    }

    @Test
    void notJsonAtAllIsAnInvalidExport() {
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, failure("not json".getBytes(), built.request()));
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, failure(new byte[0], built.request()));
        assertSame(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, failure("[]".getBytes(), built.request()));
    }
}
