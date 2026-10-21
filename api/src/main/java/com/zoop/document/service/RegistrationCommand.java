package com.zoop.document.service;

import java.time.Instant;
import java.time.LocalDate;

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
 * @param publisher    operator-declared publishing outlet of this version, or null when none was declared; version-bound, so a
 *                     later different value for the same version is a {@code version_conflict}
 * @param publishedAt  set only for the {@code datetime} precision; never a guessed value
 * @param publishedDate set only for the {@code day} precision: a calendar date that is never widened to a midnight
 * @param publicationPrecision the registry's precision vocabulary: {@code datetime}, {@code day} or {@code unknown}
 * @param collectedAt  time of the observation; kept only if this is the first registered observation. For a document collected
 *                     over HTTP this is the actual fetch time, otherwise the S2-1 page receipt time
 */
public record RegistrationCommand(String articleId, String version, String provider, ArticleKind kind,
        String textArtifactId, String storageUri, String sha256, long bytes, String title, String url, String publisher,
        Instant publishedAt, LocalDate publishedDate, String publicationPrecision, Instant collectedAt,
        PointerPolicy pointer) {
}
