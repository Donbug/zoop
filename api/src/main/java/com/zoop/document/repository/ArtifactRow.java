package com.zoop.document.repository;

import java.time.Instant;

public record ArtifactRow(String id, String kind, String storageUri, String sha256, long bytes, String mediaType,
        Instant createdAt) {
}
