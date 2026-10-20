package com.zoop.document.importer;

import java.time.Instant;
import java.time.LocalDate;

import tools.jackson.databind.JsonNode;

/**
 * A S2-1 export that passed every check against the request. Identity strings are the export's own, byte for byte.
 *
 * @param textArtifactId the export's {@code textArtifactId} ({@code "text-" + documentVersion})
 * @param textUtf8       the strict UTF-8 encoding of the text; this is what is stored and hashed as the artifact
 * @param url            the normalized URL of this observation
 * @param publishedAt    set only for the {@code datetime} precision; null otherwise
 * @param publishedDate  set only for the {@code day} precision (a calendar date, never a midnight); null otherwise
 * @param publicationPrecision {@code datetime}, {@code day} or {@code unknown}, the registry's own vocabulary. A declared time
 *                       without a UTC offset is stored as {@code unknown} (its raw form is kept in {@code collected})
 * @param observedAt     page receipt time of this observation in the S2-1 ledger
 * @param collected      acquisition facts when the observation was collected over HTTP; null for authored fixtures
 * @param document       the export's {@code document} object, exactly as validated: the S1 {@code Document} of the AI contract
 *                       (the key set is closed; {@code rawLocators} is only known to be an array)
 */
public record VerifiedDocument(Observation observation, String textArtifactId, String text, byte[] textUtf8,
        String title, String url, Instant publishedAt, LocalDate publishedDate, String publicationPrecision,
        Instant observedAt, String grantId, String grantRevision, CollectedProvenance collected, JsonNode document) {

    @Override
    public String toString() {
        return "VerifiedDocument[" + observation.documentVersion() + "]";
    }
}
