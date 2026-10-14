package com.zoop.document.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** ERD v6 section 15. Only {@code access_status} and {@code current_version} are mutable (enforced by a DB trigger). */
@Entity
@Table(name = "articles")
public class Article {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "kind", nullable = false, columnDefinition = "text")
    private String kind;

    @Column(name = "provider", nullable = false, columnDefinition = "text")
    private String provider;

    @Column(name = "provider_key", columnDefinition = "text")
    private String providerKey;

    @Column(name = "lineage_key", columnDefinition = "text")
    private String lineageKey;

    @Column(name = "current_version", columnDefinition = "text")
    private String currentVersion;

    @Column(name = "access_status", nullable = false, columnDefinition = "text")
    private String accessStatus;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    protected Article() {
    }
}
