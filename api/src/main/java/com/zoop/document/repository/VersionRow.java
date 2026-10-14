package com.zoop.document.repository;

import java.time.Instant;
import java.time.LocalDate;

public record VersionRow(String articleId, String version, String title, String publisher, String url,
        Instant publishedAt, LocalDate publishedDate, String publicationPrecision, String rawArtifactId,
        String textArtifactId, Instant collectedAt) {
}
