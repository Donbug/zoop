package com.zoop.graph.importer;

import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;

/**
 * Where the importer gets the CURRENT handoff from: the installed {@code zoop-ai-handoff export} ({@link CliHandoffSource}) or
 * ai/service's read-only handoff HTTP ({@link HttpHandoffSource}). Nothing is cached. {@link #fetch} is the complete answer
 * (manifest, bundle, the producer's verification) that the import checks and later writes: the two digests are recomputed here
 * from the manifest and bundle received and compared with the operator's pins, and the bundle goes through the app's own
 * verifier. {@link #current} is the look right before the commit, which needs only the digests the producer stands behind at
 * that moment (the CLI exports again; the HTTP source asks the content-free status route), under the same delivery and pin
 * rules.
 */
public interface HandoffSource {

    /**
     * @throws GraphHandoffException {@code handoff_refused} (a structured refusal of the producer or the service),
     *         {@code handoff_withheld} (not deliverable under current authority; no content), {@code handoff_export_unavailable}
     *         (could not run, reach or answer), {@code handoff_export_invalid} (an answer outside the contract),
     *         {@code pin_mismatch}, {@code bundle_invalid} or {@code review_state_changed}
     */
    VerifiedHandoff fetch(GraphHandoffRequest request);

    /**
     * The digests of the handoff as the producer delivers it now, checked against the operator's pins the way {@link #fetch}
     * checks them (a moved handoff is {@code pin_mismatch} or {@code handoff_withheld} here too).
     *
     * @throws GraphHandoffException as {@link #fetch}
     */
    Current current(GraphHandoffRequest request);

    /** The two digests the producer currently stands behind. */
    record Current(String manifestDigest, String bundleDigest) {
    }
}
