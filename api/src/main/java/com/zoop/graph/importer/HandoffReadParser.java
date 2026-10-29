package com.zoop.graph.importer;

import java.util.HashSet;

import com.zoop.ai.handoff.HandoffReadClient.HandoffRead;
import com.zoop.ai.handoff.HandoffReadClient.Verification;
import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.graph.importer.HandoffBundleVerifier.Manifest;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Verifies one {@code getGraphHandoffBundle} answer against the request the operator made, in the same order and to the same
 * depth as {@link HandoffExportParser} verifies a CLI export:
 * <ol>
 * <li>the delivery is current (a withheld answer is {@code handoff_withheld} with the service's reason) and the handoff is
 *     {@code ready} with a manifest and a bundle;</li>
 * <li>the manifest and the bundle are re-serialized as the producer's canonical JSON and hashed here: their digests must be the
 *     two the operator pinned in the request ({@code pin_mismatch}, nothing else is read);</li>
 * <li>the service's {@code verification} agrees with what was recomputed (digests, size, content digest, counts, provenance,
 *     number of sources);</li>
 * <li>the manifest and the bundle are validated in full ({@link HandoffBundleVerifier}) and agree with each other on identity,
 *     declaration, policy version, operator file pins and source pins.</li>
 * </ol>
 * The review state check the CLI reports as {@code delivery.reviewDigestMatches} is part of what the producer verifies before
 * it answers {@code current} (its {@code used_review_revisions_unchanged} check), and the service never delivers content
 * otherwise; a change shows up as a withheld {@code review_revision_changed}. The receipt keeps the service's answer minus the
 * content under {@code producer.read}. {@link #current} applies steps 1 and 2 to a {@code getGraphHandoffStatus} answer, the
 * look right before the commit.
 */
public final class HandoffReadParser {
    static final String TRANSPORT = "internal-http";
    static final String SCHEMA_VERSION = com.zoop.ai.http.HandoffWire.ENVELOPE_SCHEMA;

    public VerifiedHandoff parse(HandoffRead read, GraphHandoffRequest request) {
        try {
            return verify(read, request);
        } catch (StrictJson.Malformed malformed) {
            throw new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_INVALID);
        }
    }

    /**
     * One {@code getGraphHandoffStatus} answer as the look right before the commit: the same identity, delivery, state and pin
     * checks as {@link #parse}, over the digests the service reports. There is no content to recompute them from; the content
     * the import writes is the one {@link #parse} verified, and equal digests mean the producer still stands behind exactly it.
     */
    public HandoffSource.Current current(HandoffRead read, GraphHandoffRequest request) {
        try {
            Verification verification = delivered(read, request);
            if (!verification.manifestDigest().equals(request.expectedManifestDigest())
                    || !verification.bundleDigest().equals(request.expectedBundleDigest())) {
                throw new GraphHandoffException(GraphHandoffFailure.PIN_MISMATCH);
            }
            return new HandoffSource.Current(verification.manifestDigest(), verification.bundleDigest());
        } catch (StrictJson.Malformed malformed) {
            throw new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_INVALID);
        }
    }

    /** Step 1 of both routes: the requested handoff, delivered (else withheld with the service's reason), ready, verified. */
    private static Verification delivered(HandoffRead read, GraphHandoffRequest request) {
        need(request.handoffId().equals(read.handoffId()));
        if (!read.current()) {
            throw GraphHandoffException.handoffWithheld(read.delivery().reason().orElse("withheld"));
        }
        need("ready".equals(read.state()));
        return read.verification().orElseThrow(StrictJson.Malformed::new);
    }

    private static VerifiedHandoff verify(HandoffRead read, GraphHandoffRequest request) {
        Verification verification = delivered(read, request);
        JsonNode manifestNode = read.manifest().orElseThrow(StrictJson.Malformed::new);
        JsonNode bundleNode = read.bundle().orElseThrow(StrictJson.Malformed::new);
        need(manifestNode.isObject() && bundleNode.isObject());

        String manifestDigest = Canonical.digest(manifestNode);
        byte[] bundleBytes = Canonical.bytes(bundleNode);
        String bundleDigest = Canonical.sha256(bundleBytes);
        if (!manifestDigest.equals(request.expectedManifestDigest()) || !bundleDigest.equals(request.expectedBundleDigest())) {
            throw new GraphHandoffException(GraphHandoffFailure.PIN_MISMATCH);
        }
        need(bundleBytes.length <= HandoffExportParser.MAX_BUNDLE_BYTES);

        HandoffBundle bundle;
        try {
            bundle = HandoffBundleVerifier.verify(bundleNode);
        } catch (StrictJson.Malformed malformed) {
            throw new GraphHandoffException(GraphHandoffFailure.BUNDLE_INVALID);
        }
        Manifest manifest = HandoffBundleVerifier.verifyManifest(manifestNode);
        String contentDigest = HandoffBundleVerifier.contentDigest(bundleNode);

        need(manifestDigest.equals(verification.manifestDigest()) && bundleDigest.equals(verification.bundleDigest())
                && contentDigest.equals(verification.contentDigest()) && verification.bundleBytes() == bundleBytes.length
                && bundleNode.get("counts").equals(verification.counts())
                && bundleNode.get("provenance").equals(verification.provenance())
                && bundleNode.get("sources").size() == verification.sources());

        need(manifest.handoffId().equals(bundle.handoffId()) && bundle.handoffId().equals(request.handoffId())
                && manifestDigest.equals(bundle.manifestDigest()) && manifest.sourceKind().equals(bundle.sourceKind())
                && manifest.policyVersion().equals(bundle.policyVersion()) && manifest.files().equals(bundle.files())
                && manifest.sources().size() == bundle.sources().size()
                && new HashSet<>(manifest.sources()).equals(new HashSet<>(bundle.sources())));

        return new VerifiedHandoff(bundle, manifest, manifestNode, bundleNode, producer(read, verification), manifestDigest,
                bundleDigest, contentDigest);
    }

    /** {@code producer.read}: the service's answer without its content, so the receipt says where the bundle came from. */
    static ObjectNode producer(HandoffRead read, Verification verification) {
        ObjectNode answer = StrictJson.newObject();
        answer.put("schemaVersion", SCHEMA_VERSION);
        answer.put("transport", TRANSPORT);
        answer.put("handoffId", read.handoffId());
        answer.put("state", read.state());
        ObjectNode delivery = answer.putObject("delivery");
        delivery.put("state", read.delivery().state());
        delivery.put("checkedAt", read.delivery().checkedAt().orElse(null));
        ObjectNode verified = answer.putObject("verification");
        verified.put("manifestDigest", verification.manifestDigest());
        verified.put("bundleDigest", verification.bundleDigest());
        verified.put("contentDigest", verification.contentDigest());
        verified.put("bundleBytes", verification.bundleBytes());
        verified.set("counts", verification.counts());
        verified.put("sources", verification.sources());
        verified.set("provenance", verification.provenance());
        answer.put("observedAt", read.observedAt());
        ObjectNode producer = StrictJson.newObject();
        producer.set("read", answer);
        return producer;
    }

    private static void need(boolean condition) {
        if (!condition) {
            throw new StrictJson.Malformed();
        }
    }
}
