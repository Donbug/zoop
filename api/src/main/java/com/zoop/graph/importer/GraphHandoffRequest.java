package com.zoop.graph.importer;

/**
 * One operator request to stage one AI handoff as an inactive graph version.
 *
 * @param handoffId              the AI handoff to import (up to 200 characters)
 * @param expectedManifestDigest the SHA-256 the operator pins for the frozen manifest (its canonical JSON)
 * @param expectedBundleDigest   the SHA-256 the operator pins for the frozen bundle (its canonical JSON)
 * @param operator               who runs the import; recorded as {@code graph_versions.created_by = "operator:<operator>"}
 */
public record GraphHandoffRequest(String handoffId, String expectedManifestDigest, String expectedBundleDigest,
        String operator) {
}
