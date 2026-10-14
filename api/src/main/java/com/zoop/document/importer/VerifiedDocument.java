package com.zoop.document.importer;

import java.time.Instant;

import tools.jackson.databind.JsonNode;

/**
 * A S2-1 export that passed every check against the request. Identity strings are the export's own, byte for byte.
 *
 * @param textArtifactId the export's {@code textArtifactId} ({@code "text-" + documentVersion})
 * @param textUtf8       the strict UTF-8 encoding of the text; this is what is stored and hashed as the artifact
 * @param url            the normalized URL of this observation
 * @param publishedAt    null when the source gave no publication time
 * @param observedAt     page receipt time of this observation in the S2-1 ledger
 * @param document       the export's {@code document} object, exactly as validated: the S1 {@code Document} of the AI contract
 *                       (the key set is closed; {@code rawLocators} is only known to be an array)
 */
public record VerifiedDocument(Observation observation, String textArtifactId, String text, byte[] textUtf8,
        String title, String url, Instant publishedAt, Instant observedAt, String grantId, String grantRevision, JsonNode document) {

    @Override
    public String toString() {
        return "VerifiedDocument[" + observation.documentVersion() + "]";
    }
}
