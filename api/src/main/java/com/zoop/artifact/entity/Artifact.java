package com.zoop.artifact.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * ERD v6 section 14. Immutable file registry row; the importer writes it through JDBC and this mapping exists so that
 * {@code ddl-auto: validate} checks the Flyway schema.
 */
@Entity
@Table(name = "artifacts")
public class Artifact {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "kind", nullable = false, columnDefinition = "text")
    private String kind;

    @Column(name = "storage_uri", nullable = false, columnDefinition = "text")
    private String storageUri;

    @Column(name = "sha256", nullable = false, columnDefinition = "text")
    private String sha256;

    @Column(name = "bytes", nullable = false, columnDefinition = "bigint")
    private long bytes;

    @Column(name = "media_type", nullable = false, columnDefinition = "text")
    private String mediaType;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    protected Artifact() {
    }
}
