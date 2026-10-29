package com.zoop.graph.importer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Optional;
import java.util.OptionalInt;

import com.zoop.ai.AiOperation;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.HandoffServiceErrorException;
import com.zoop.ai.handoff.HandoffReadClient;
import com.zoop.ai.handoff.HandoffReadClient.HandoffRead;
import com.zoop.ai.handoff.HandoffReadClient.Verification;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import com.zoop.graph.importer.HandoffFixtures.Built;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/** The HTTP source verifies a {@code getGraphHandoffBundle} answer to the same depth as the CLI export parser. */
class HttpHandoffSourceTest {
    private final Built built = HandoffFixtures.build();

    private static HttpHandoffSource source(HandoffRead answer) {
        return new HttpHandoffSource(new HandoffFixtures.FakeHandoffRead(answer));
    }

    private static HttpHandoffSource failing(RuntimeException failure) {
        return new HttpHandoffSource(new HandoffReadClient() {
            @Override
            public HandoffRead status(String handoffId) {
                throw failure;
            }

            @Override
            public HandoffRead bundle(String handoffId) {
                throw failure;
            }
        });
    }

    private static GraphHandoffException failure(HttpHandoffSource source, GraphHandoffRequest request) {
        return assertThrows(GraphHandoffException.class, () -> source.fetch(request));
    }

    @Test
    void aCurrentAnswerVerifiesToExactlyWhatTheCliExportVerifiesToAndRecordsTheReadInTheReceipt() {
        VerifiedHandoff cli = new HandoffExportParser().parse(built.envelopeBytes(), built.request());
        VerifiedHandoff http = source(HandoffFixtures.read(built)).fetch(built.request());

        assertEquals(cli.manifestDigest(), http.manifestDigest());
        assertEquals(cli.bundleDigest(), http.bundleDigest());
        assertEquals(cli.contentDigest(), http.contentDigest());
        assertEquals(cli.bundle(), http.bundle());
        assertEquals(cli.manifest(), http.manifest());
        assertEquals(cli.bundleNode(), http.bundleNode());
        assertEquals(cli.manifestNode(), http.manifestNode());
        // What the receipt retains says where the bundle came from: the service's answer minus its content.
        JsonNode read = http.producerNode().get("read");
        assertEquals(1, http.producerNode().size());
        assertEquals(HandoffReadParser.TRANSPORT, read.get("transport").stringValue());
        assertEquals("zoop-ai-internal-handoff-1", read.get("schemaVersion").stringValue());
        assertEquals("current", read.get("delivery").get("state").stringValue());
        assertEquals(built.bundleDigest(), read.get("verification").get("bundleDigest").stringValue());
        assertEquals(built.bundle().get("counts"), read.get("verification").get("counts"));
        assertFalse(read.has("bundle"));
        assertFalse(read.has("manifest"));
        // The per-request stamps are not part of the receipt: the same pins must produce the same receipt bytes.
        assertFalse(read.has("observedAt"));
        assertFalse(read.get("delivery").has("checkedAt"));
    }

    @Test
    void theLookBeforeTheCommitIsTheContentFreeStatusRouteUnderTheSameDeliveryAndPinRules() {
        HandoffFixtures.FakeHandoffRead reads = new HandoffFixtures.FakeHandoffRead(HandoffFixtures.read(built));
        HttpHandoffSource source = new HttpHandoffSource(reads);

        HandoffSource.Current current = source.current(built.request());

        assertEquals(built.manifestDigest(), current.manifestDigest());
        assertEquals(built.bundleDigest(), current.bundleDigest());
        assertEquals(1, reads.statusCalls.get());
        assertEquals(0, reads.bundleCalls.get());

        GraphHandoffRequest otherPins = new GraphHandoffRequest(built.spec().handoffId(), "1".repeat(64), built.bundleDigest(), "operator-a");
        assertEquals(GraphHandoffFailure.PIN_MISMATCH,
                assertThrows(GraphHandoffException.class, () -> source.current(otherPins)).failure());
        GraphHandoffException withheld = assertThrows(GraphHandoffException.class,
                () -> source(HandoffFixtures.withheld(built.spec().handoffId(), "upstream_changed")).current(built.request()));
        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, withheld.failure());
        assertEquals("upstream_changed", withheld.cliCode());
        HandoffRead read = HandoffFixtures.read(built);
        HandoffRead notReady = new HandoffRead(read.handoffId(), "reserved", read.delivery(), read.verification(), Optional.empty(),
                Optional.empty(), read.observedAt());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID,
                assertThrows(GraphHandoffException.class, () -> source(notReady).current(built.request())).failure());
    }

    @Test
    void aWithheldAnswerIsWithheldWithTheServicesReasonAndNeverContent() {
        GraphHandoffException withheld = failure(source(HandoffFixtures.withheld(built.spec().handoffId(), "review_revision_changed")),
                built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, withheld.failure());
        assertEquals("review_revision_changed", withheld.cliCode());
        // A reason in the service's wider alphabet reaches the result as well (never dropped to null).
        GraphHandoffException wide = failure(source(HandoffFixtures.withheld(built.spec().handoffId(), "Review.Changed:s3-revoked")),
                built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_WITHHELD, wide.failure());
        assertEquals("Review.Changed:s3-revoked", wide.cliCode());
    }

    @Test
    void theOperatorsPinsAreCheckedAgainstTheBytesReceivedBeforeAnythingElse() {
        GraphHandoffRequest otherPins = new GraphHandoffRequest(built.spec().handoffId(), "1".repeat(64), built.bundleDigest(), "operator-a");
        assertEquals(GraphHandoffFailure.PIN_MISMATCH, failure(source(HandoffFixtures.read(built)), otherPins).failure());

        // The service says the bundle is something else than what it delivered: not a pin problem, an answer outside the contract.
        HandoffRead read = HandoffFixtures.read(built);
        Verification v = read.verification().orElseThrow();
        HandoffRead disagreeing = new HandoffRead(read.handoffId(), read.state(), read.delivery(),
                Optional.of(new Verification(v.manifestDigest(), v.bundleDigest(), v.contentDigest(), v.bundleBytes() + 1, v.counts(),
                        v.sources(), v.provenance())), read.manifest(), read.bundle(), read.observedAt());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, failure(source(disagreeing), built.request()).failure());
        HandoffRead notReady = new HandoffRead(read.handoffId(), "reserved", read.delivery(), read.verification(), read.manifest(),
                read.bundle(), read.observedAt());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, failure(source(notReady), built.request()).failure());
    }

    @Test
    void aBundleThatBreaksAProducerRuleIsInvalidEvenWhenItsPinsAndVerificationMatch() {
        Built forged = HandoffFixtures.repinned(built, bundle -> ((ObjectNode) bundle.get("policy")).put("version", "zoop-public-projection-policy-9"));
        GraphHandoffRequest pins = new GraphHandoffRequest(forged.spec().handoffId(), forged.manifestDigest(), forged.bundleDigest(), "operator-a");
        assertEquals(GraphHandoffFailure.BUNDLE_INVALID, failure(source(HandoffFixtures.read(forged)), pins).failure());
    }

    @Test
    void serviceRefusalsAndTransportFailuresMapOntoTheImportersCodes() {
        GraphHandoffException refused = failure(failing(new HandoffServiceErrorException(AiOperation.HANDOFF_READ, "r-1", 403,
                "handoff_not_allowed", false, Optional.empty(), Optional.empty(), Optional.empty())), built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_REFUSED, refused.failure());
        assertEquals("handoff_not_allowed", refused.cliCode());

        GraphHandoffException busy = failure(failing(new HandoffServiceErrorException(AiOperation.HANDOFF_READ, "r-2", 503,
                "runtime_busy", true, Optional.of("handoff_busy"), Optional.empty(), Optional.empty())), built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE, busy.failure());

        GraphHandoffException unreachable = failure(failing(new AiTransportException(AiOperation.HANDOFF_READ, "r-3",
                AiTransportException.Failure.CONNECT_FAILED, OptionalInt.empty(), null)), built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE, unreachable.failure());
        assertTrue(unreachable.cliCode() == null);

        // An answer outside the contract is invalid, not a transient failure: a retry would not do better.
        GraphHandoffException malformed = failure(failing(new AiTransportException(AiOperation.HANDOFF_READ, "r-5",
                AiTransportException.Failure.RESPONSE_MALFORMED, OptionalInt.of(200), null)), built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, malformed.failure());
        GraphHandoffException tooLarge = failure(failing(new AiTransportException(AiOperation.HANDOFF_READ, "r-6",
                AiTransportException.Failure.RESPONSE_TOO_LARGE, OptionalInt.of(200), null)), built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_INVALID, tooLarge.failure());
        GraphHandoffException timedOut = failure(failing(new AiTransportException(AiOperation.HANDOFF_READ, "r-7",
                AiTransportException.Failure.TIMEOUT, OptionalInt.empty(), null)), built.request());
        assertEquals(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE, timedOut.failure());

        // The status route maps the same way.
        HttpHandoffSource notAllowed = failing(new HandoffServiceErrorException(AiOperation.HANDOFF_READ, "r-4", 403,
                "handoff_not_allowed", false, Optional.empty(), Optional.empty(), Optional.empty()));
        assertEquals(GraphHandoffFailure.HANDOFF_REFUSED,
                assertThrows(GraphHandoffException.class, () -> notAllowed.current(built.request())).failure());
    }
}
