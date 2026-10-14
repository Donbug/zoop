package com.zoop.document.entity;

import java.time.Instant;
import java.time.LocalDate;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

/** ERD v6 section 16. Immutable once inserted (enforced by a DB trigger). */
@Entity
@Table(name = "article_versions")
@IdClass(ArticleVersionId.class)
public class ArticleVersion {
    @Id
    @Column(name = "article_id", nullable = false, columnDefinition = "text")
    private String articleId;

    @Id
    @Column(name = "version", nullable = false, columnDefinition = "text")
    private String version;

    @Column(name = "title", columnDefinition = "text")
    private String title;

    @Column(name = "publisher", columnDefinition = "text")
    private String publisher;

    @Column(name = "url", columnDefinition = "text")
    private String url;

    @Column(name = "published_at", columnDefinition = "timestamptz")
    private Instant publishedAt;

    @Column(name = "published_date", columnDefinition = "date")
    private LocalDate publishedDate;

    @Column(name = "publication_precision", nullable = false, columnDefinition = "text")
    private String publicationPrecision;

    @Column(name = "raw_artifact_id", columnDefinition = "text")
    private String rawArtifactId;

    @Column(name = "text_artifact_id", nullable = false, columnDefinition = "text")
    private String textArtifactId;

    @Column(name = "collected_at", nullable = false, columnDefinition = "timestamptz")
    private Instant collectedAt;

    protected ArticleVersion() {
    }
}
