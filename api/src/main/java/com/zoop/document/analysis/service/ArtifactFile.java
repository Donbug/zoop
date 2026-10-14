package com.zoop.document.analysis.service;

/** A JSON artifact file already stored in the artifact root, to be registered in {@code artifacts} ({@code application/json}). */
public record ArtifactFile(String id, String kind, String uri, String sha256, long bytes) {
}
