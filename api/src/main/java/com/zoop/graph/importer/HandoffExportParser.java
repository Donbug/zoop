package com.zoop.graph.importer;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.zoop.common.json.Canonical;
import com.zoop.common.json.StrictJson;
import com.zoop.common.json.StrictJson.Obj;
import com.zoop.graph.importer.HandoffBundleVerifier.Manifest;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Validates one {@code zoop-ai-handoff export} envelope against the request the operator made. In this order:
 * <ol>
 * <li>the envelope is exactly what the CLI prints for a current delivery (closed keys, {@code state=ready},
 *     {@code publication=not-published}, {@code delivery.status=current}, zero provider and model calls);</li>
 * <li>the manifest and the bundle are re-serialized as the producer's canonical JSON and hashed here: their digests must be the
 *     two the operator pinned in the request ({@code pin_mismatch}, nothing else is read);</li>
 * <li>the producer's receipt agrees with what was recomputed (digests, size, content digest, provenance, sources, files,
 *     counts, exclusion codes, checks);</li>
 * <li>the manifest and the bundle are validated in full ({@link HandoffBundleVerifier}) and agree with each other on identity,
 *     declaration, policy version, operator file pins and source pins;</li>
 * <li>{@code delivery.reviewDigestMatches} is true: the whole pinned review state of every S3 job still equals the freeze.</li>
 * </ol>
 * Anything else is a code, never a partial read.
 */
public final class HandoffExportParser {
    public static final int MAX_BUNDLE_BYTES = 6 * 1024 * 1024;

    private static final Set<String> TOP = Set.of("schemaVersion", "handoffId", "state", "publication", "next", "failure",
            "receipt", "attempts", "usage", "delivery", "manifest", "bundle");
    private static final Set<String> RECEIPT = Set.of("handoffId", "manifestDigest", "bundleSchema", "bundleDigest",
            "contentDigest", "bundleBytes", "provenance", "sources", "files", "counts", "exclusionCodes", "checks", "frozenAt");
    private static final List<String> DELIVERY_CHECKS = List.of("operator_files_equal_manifest_pins",
            "s3_authority_and_s2_upstream_pin_current", "used_review_revisions_unchanged", "content_digest_rebuilt_equal");
    private static final Set<String> ATTEMPT_KINDS = Set.of("freeze", "recover");
    private static final Set<String> ATTEMPT_OUTCOMES = Set.of("written", "confirmed", "artifact-missing", "artifact-invalid");

    /**
     * A current, fully verified handoff: the typed bundle plus the original objects the receipt artifact retains.
     * {@code producerNode} is what the receipt keeps under {@code producer}: for a CLI export its {@code receipt} and
     * {@code attempts}, for an HTTP read the service's {@code read} answer (see {@link HandoffReadParser}).
     */
    public record VerifiedHandoff(HandoffBundle bundle, Manifest manifest, JsonNode manifestNode, JsonNode bundleNode,
            JsonNode producerNode, String manifestDigest, String bundleDigest, String contentDigest) {
    }

    /** The {@code producer} object of a receipt built from a CLI export: the producer's own receipt and its attempts. */
    static ObjectNode producer(JsonNode receiptNode, JsonNode attemptsNode) {
        ObjectNode producer = StrictJson.newObject();
        producer.set("receipt", receiptNode);
        producer.set("attempts", attemptsNode);
        return producer;
    }

    public VerifiedHandoff parse(byte[] export, GraphHandoffRequest request) {
        try {
            return verify(StrictJson.parseObject(export), request);
        } catch (StrictJson.Malformed malformed) {
            throw new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_INVALID);
        }
    }

    private static VerifiedHandoff verify(Obj root, GraphHandoffRequest request) {
        root.exactly(TOP);
        need(ProcessHandoffExporter.SCHEMA_VERSION.equals(root.string("schemaVersion")));
        need(request.handoffId().equals(root.string("handoffId")));
        need("ready".equals(root.string("state")));
        need("not-published".equals(root.string("publication")));
        need("export".equals(root.string("next")));
        need(root.isNull("failure"));
        Obj usage = root.object("usage").exactly(Set.of("providerCalls", "modelCalls"));
        need(usage.count("providerCalls") == 0 && usage.count("modelCalls") == 0);

        Obj delivery = root.object("delivery").exactly(Set.of("status", "checkedAt", "reviewDigestMatches", "checks"));
        need("current".equals(delivery.string("status")));
        delivery.string("checkedAt");
        boolean reviewMatches = delivery.bool("reviewDigestMatches");
        need(delivery.strings("checks").equals(DELIVERY_CHECKS));

        JsonNode attempts = root.array("attempts");
        need(attempts.size() <= 5);
        for (JsonNode item : attempts.values()) {
            Obj attempt = Obj.of(item).exactly(Set.of("n", "kind", "outcome", "code"));
            need(attempt.count("n") >= 1 && ATTEMPT_KINDS.contains(attempt.string("kind"))
                    && ATTEMPT_OUTCOMES.contains(attempt.string("outcome")));
            attempt.stringOrNull("code");
        }

        JsonNode manifestNode = root.object("manifest").node();
        JsonNode bundleNode = root.object("bundle").node();
        String manifestDigest = Canonical.digest(manifestNode);
        byte[] bundleBytes = Canonical.bytes(bundleNode);
        String bundleDigest = Canonical.sha256(bundleBytes);
        if (!manifestDigest.equals(request.expectedManifestDigest()) || !bundleDigest.equals(request.expectedBundleDigest())) {
            throw new GraphHandoffException(GraphHandoffFailure.PIN_MISMATCH);
        }
        need(bundleBytes.length <= MAX_BUNDLE_BYTES);

        HandoffBundle bundle;
        try {
            bundle = HandoffBundleVerifier.verify(bundleNode);
        } catch (StrictJson.Malformed malformed) {
            throw new GraphHandoffException(GraphHandoffFailure.BUNDLE_INVALID);
        }
        Manifest manifest = HandoffBundleVerifier.verifyManifest(manifestNode);
        String contentDigest = HandoffBundleVerifier.contentDigest(bundleNode);

        Obj receipt = root.object("receipt").exactly(RECEIPT);
        need(request.handoffId().equals(receipt.string("handoffId")) && manifestDigest.equals(receipt.string("manifestDigest"))
                && HandoffBundleVerifier.BUNDLE_SCHEMA.equals(receipt.string("bundleSchema"))
                && bundleDigest.equals(receipt.string("bundleDigest")) && contentDigest.equals(receipt.string("contentDigest"))
                && receipt.count("bundleBytes") == bundleBytes.length);
        receipt.string("frozenAt");
        JsonNode receiptNode = receipt.node();
        need(bundleNode.get("provenance").equals(receiptNode.get("provenance")));
        need(sourcePins(bundleNode.get("sources")).equals(receiptNode.get("sources")));
        need(bundleNode.get("policy").get("files").equals(receiptNode.get("files")));
        need(bundleNode.get("counts").equals(receiptNode.get("counts")));
        need(bundleNode.get("exclusions").get("counts").equals(receiptNode.get("exclusionCodes")));
        need(bundleNode.get("checks").equals(receiptNode.get("checks")));

        need(manifest.handoffId().equals(bundle.handoffId()) && bundle.handoffId().equals(request.handoffId())
                && manifestDigest.equals(bundle.manifestDigest()) && manifest.sourceKind().equals(bundle.sourceKind())
                && manifest.policyVersion().equals(bundle.policyVersion()) && manifest.files().equals(bundle.files())
                && manifest.sources().size() == bundle.sources().size()
                && new HashSet<>(manifest.sources()).equals(new HashSet<>(bundle.sources())));

        if (!reviewMatches) {
            throw new GraphHandoffException(GraphHandoffFailure.REVIEW_STATE_CHANGED);
        }
        return new VerifiedHandoff(bundle, manifest, manifestNode, bundleNode, producer(receiptNode, attempts), manifestDigest,
                bundleDigest, contentDigest);
    }

    /** {@code [{relation, upstream, reviewDigest}]} in bundle order: what the producer's receipt lists as {@code sources}. */
    private static JsonNode sourcePins(JsonNode sources) {
        ArrayNode pins = StrictJson.newArray();
        List<JsonNode> list = new ArrayList<>(sources.values());
        for (JsonNode source : list) {
            ObjectNode pin = StrictJson.newObject();
            pin.set("relation", source.get("relation"));
            pin.set("upstream", source.get("upstream"));
            pin.set("reviewDigest", source.get("reviewDigest"));
            pins.add(pin);
        }
        return pins;
    }

    private static void need(boolean condition) {
        if (!condition) {
            throw new StrictJson.Malformed();
        }
    }
}
