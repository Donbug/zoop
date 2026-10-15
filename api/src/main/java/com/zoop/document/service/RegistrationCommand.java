package com.zoop.document.service;

import java.time.Instant;

/**
 * One verified document version, ready to register. Identity strings are the S2-1 export values, unmodified:
 * {@code articleId} is the S2-1 {@code documentId}, {@code version} the {@code documentVersion} and {@code textArtifactId}
 * the export's {@code textArtifactId}.
 *
 * @param provider     the S2-1 sourceId
 * @param storageUri   relative artifact URI of the stored extracted text
 * @param sha256       lowercase hex SHA-256 of the stored UTF-8 bytes (not the S2-1 sourceHash)
 * @param bytes        length of the stored UTF-8 bytes
 * @param title        version-bound title, possibly empty
 * @param url          normalized URL of the observation; kept only if this is the first registered observation
 * @param publishedAt  null when the source gave no publication time; never a guessed value
 * @param collectedAt  page receipt time of the observation; kept only if this is the first registered observation
 */
public record RegistrationCommand(String articleId, String version, String provider, ArticleKind kind,
        String textArtifactId, String storageUri, String sha256, long bytes, String title, String url,
        Instant publishedAt, Instant collectedAt, PointerPolicy pointer) {
}
