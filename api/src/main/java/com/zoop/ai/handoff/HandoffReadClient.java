package com.zoop.ai.handoff;

import java.util.Optional;

import tools.jackson.databind.JsonNode;

/**
 * The read-only handoff family of ai/service (scope {@code handoff.read}, schema {@code zoop-ai-internal-handoff-1}):
 * {@code getGraphHandoffStatus} and {@code getGraphHandoffBundle}. Every answer is the AI side's verification of ONE allowlisted
 * handoff at the moment of the request (api/docs/GRAPH_READ_HANDOFF.md "handoff bundle 내부 HTTP 읽기"): the producer's current
 * authority, the operator's two pins and the closed bundle model. It is never an app import, an activation or a public read, and
 * a withheld answer is not "no data".
 *
 * <p>What comes back is untrusted: the caller recomputes both digests from the manifest and bundle it received and validates the
 * bundle with its own verifier, exactly as it does for a CLI export.
 */
public interface HandoffReadClient {

    /** The content-free status route; {@code verification} only while current. */
    HandoffRead status(String handoffId);

    /** The bundle route; {@code manifest} and {@code bundle} only while current and both pins match the operator's. */
    HandoffRead bundle(String handoffId);

    /**
     * One decoded answer. {@code state} is the producer's ledger state ({@code reserved}, {@code ready} or {@code failed});
     * {@code publication} is always {@code not-published} and {@code appImport} always {@code pending}, so neither is carried.
     *
     * @param observedAt the service's own time of the answer (an opaque stamp, retained for the receipt)
     */
    record HandoffRead(String handoffId, String state, Delivery delivery, Optional<Verification> verification,
            Optional<JsonNode> manifest, Optional<JsonNode> bundle, String observedAt) {
        public boolean current() {
            return "current".equals(delivery.state());
        }
    }

    /** {@code delivery}: {@code current} with the producer's check time, or {@code withheld} with a reason code. */
    record Delivery(String state, Optional<String> reason, Optional<String> checkedAt) {
    }

    /** {@code verification}: the digests and counts the service computed over the bytes it delivered. */
    record Verification(String manifestDigest, String bundleDigest, String contentDigest, long bundleBytes, JsonNode counts,
            int sources, JsonNode provenance) {
    }
}
