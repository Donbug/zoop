package com.zoop.ai.http;

import java.net.URI;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

import com.zoop.ai.AiClientSettings;
import com.zoop.ai.AiOperation;
import com.zoop.ai.handoff.HandoffReadClient;
import com.zoop.ai.http.AiHttpTransport.Reply;
import com.zoop.ai.http.WireJson.Malformed;
import tools.jackson.databind.JsonNode;

/**
 * {@code GET /internal/v1/graph-handoffs/{handoffId}} and {@code .../bundle} over the shared bounded transport (no proxy,
 * redirect or retry). Both are read-only (no idempotency key, no job, no cache on the AI side). Only the {@code HdStatus} /
 * {@code HdBundle} envelope is decoded here, closed and strict; the manifest and bundle inside are the caller's to verify, and
 * so are the digests the service reports about them.
 */
public final class HttpHandoffReadClient implements HandoffReadClient, AutoCloseable {
    static final String PATH = "/internal/v1/graph-handoffs/";
    private static final Pattern HASH = Pattern.compile("[a-f0-9]{64}");
    private static final Pattern STATE = Pattern.compile("reserved|ready|failed");
    private static final Pattern DELIVERY = Pattern.compile("current|withheld");
    /** {@code delivery.checkedAt}: the one stamp the contract gives a pattern ({@code STAMP_PATTERN} on the AI side). */
    private static final Pattern STAMP = Pattern.compile("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?(Z|\\+00:00)");
    private static final Set<String> STATUS_KEYS = Set.of("schemaVersion", "handoffId", "state", "publication", "appImport",
            "delivery", "verification", "observedAt");
    private static final Set<String> BUNDLE_KEYS = Set.of("schemaVersion", "handoffId", "state", "publication", "appImport",
            "delivery", "verification", "observedAt", "manifest", "bundle");
    private static final Set<String> DELIVERY_KEYS = Set.of("state", "reason", "checkedAt");
    private static final Set<String> VERIFICATION_KEYS = Set.of("manifestDigest", "bundleDigest", "contentDigest", "bundleBytes",
            "counts", "sources", "provenance");
    private final AiHttpTransport transport;

    public HttpHandoffReadClient(AiClientSettings settings) {
        transport = new AiHttpTransport(settings);
    }

    @Override
    public HandoffRead status(String handoffId) {
        Reply reply = transport.exchange(AiOperation.HANDOFF_READ, "GET", uri(handoffId, ""), null, null,
                HandoffWire.rejections(), 200);
        return AiHttpTransport.decode(reply, () -> read(reply.body(), handoffId, false));
    }

    @Override
    public HandoffRead bundle(String handoffId) {
        Reply reply = transport.exchange(AiOperation.HANDOFF_READ, "GET", uri(handoffId, "/bundle"), null, null,
                HandoffWire.rejections(), 200);
        return AiHttpTransport.decode(reply, () -> read(reply.body(), handoffId, true));
    }

    private URI uri(String handoffId, String suffix) {
        if (handoffId == null || !HandoffWire.HANDOFF_ID.matcher(handoffId).matches()) {
            throw new IllegalArgumentException("handoffId");
        }
        return transport.uri(PATH + AiHttpTransport.segment(handoffId) + suffix);
    }

    /**
     * The {@code HdStatus} ({@code withBundle=false}) or {@code HdBundle} envelope: closed keys, the requested handoff, the
     * contract's constants, and content only while current. {@code manifest} and {@code bundle} may be absent or null when
     * withheld, and must be objects when current.
     */
    static HandoffRead read(JsonNode document, String handoffId, boolean withBundle) {
        if (document == null || !document.isObject()) throw new Malformed("handoff");
        Set<String> names = HandoffWire.names(document);
        Set<String> allowed = withBundle ? BUNDLE_KEYS : STATUS_KEYS;
        if (!allowed.containsAll(names) || !names.containsAll(Set.of("handoffId", "state", "delivery", "observedAt"))) {
            throw new Malformed("handoff");
        }
        if (names.contains("schemaVersion")) {
            JsonNode schema = document.get("schemaVersion");
            if (!schema.isString() || !HandoffWire.ENVELOPE_SCHEMA.equals(schema.stringValue())) throw new Malformed("handoff.schemaVersion");
        }
        constant(document, "publication", "not-published");
        constant(document, "appImport", "pending");
        WireJson.Obj root = WireJson.Obj.of(document, "handoff");
        if (!root.string("handoffId", HandoffWire.HANDOFF_ID).equals(handoffId)) throw new Malformed("handoff.handoffId");
        String state = root.string("state", STATE);
        // The contract types observedAt as a plain string (no pattern): an opaque, printable stamp kept for the receipt only.
        String observedAt = root.string("observedAt", AnalysisWire.TEXT);

        JsonNode deliveryNode = document.get("delivery");
        if (deliveryNode == null || !deliveryNode.isObject() || !DELIVERY_KEYS.containsAll(HandoffWire.names(deliveryNode))) {
            throw new Malformed("handoff.delivery");
        }
        WireJson.Obj delivery = WireJson.Obj.of(deliveryNode, "handoff.delivery");
        String deliveryState = delivery.string("state", DELIVERY);
        Optional<String> reason = nullable(deliveryNode, "reason") ? Optional.empty() : delivery.optString("reason", HandoffWire.REASON);
        Optional<String> checkedAt = nullable(deliveryNode, "checkedAt") ? Optional.empty() : delivery.optString("checkedAt", STAMP);
        boolean current = "current".equals(deliveryState);

        Optional<Verification> verification = Optional.empty();
        JsonNode verificationNode = document.get("verification");
        if (current) {
            if (verificationNode == null || !verificationNode.isObject() || checkedAt.isEmpty() || reason.isPresent()) {
                throw new Malformed("handoff.verification");
            }
            if (!VERIFICATION_KEYS.equals(HandoffWire.names(verificationNode))) throw new Malformed("handoff.verification");
            WireJson.Obj v = WireJson.Obj.of(verificationNode, "handoff.verification");
            JsonNode counts = verificationNode.get("counts");
            JsonNode provenance = verificationNode.get("provenance");
            if (!counts.isObject() || !provenance.isObject()) throw new Malformed("handoff.verification");
            long sources = v.count("sources");
            if (sources < 1 || sources > 20) throw new Malformed("handoff.verification.sources");
            verification = Optional.of(new Verification(v.string("manifestDigest", HASH), v.string("bundleDigest", HASH),
                    v.string("contentDigest", HASH), v.count("bundleBytes"), counts, (int) sources, provenance));
        } else if (!nullable(document, "verification") || reason.isEmpty()) {
            throw new Malformed("handoff.verification");
        }

        Optional<JsonNode> manifest = Optional.empty();
        Optional<JsonNode> bundle = Optional.empty();
        if (withBundle) {
            JsonNode manifestNode = document.get("manifest");
            JsonNode bundleNode = document.get("bundle");
            if (current) {
                if (manifestNode == null || !manifestNode.isObject() || bundleNode == null || !bundleNode.isObject()) {
                    throw new Malformed("handoff.bundle");
                }
                manifest = Optional.of(manifestNode);
                bundle = Optional.of(bundleNode);
            } else if (!nullable(document, "manifest") || !nullable(document, "bundle")) {
                throw new Malformed("handoff.bundle");
            }
        }
        return new HandoffRead(handoffId, state, new Delivery(deliveryState, reason, checkedAt), verification, manifest, bundle,
                observedAt);
    }

    /** A string field that must equal the contract's constant when present. */
    private static void constant(JsonNode document, String name, String value) {
        JsonNode node = document.get(name);
        if (node != null && (!node.isString() || !value.equals(node.stringValue()))) throw new Malformed("handoff." + name);
    }

    /** Absent or JSON null. */
    private static boolean nullable(JsonNode object, String name) {
        JsonNode node = object.get(name);
        return node == null || node.isNull();
    }

    @Override
    public void close() {
        transport.close();
    }
}
