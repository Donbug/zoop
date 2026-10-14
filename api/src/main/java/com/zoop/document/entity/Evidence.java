package com.zoop.document.entity;

import java.time.Instant;
import java.util.List;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** ERD v6 section 17. Immutable once inserted (enforced by a DB trigger); offsets are Unicode code points. */
@Entity
@Table(name = "evidence")
public class Evidence {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "article_id", nullable = false, columnDefinition = "text")
    private String articleId;

    @Column(name = "article_version", nullable = false, columnDefinition = "text")
    private String articleVersion;

    @Column(name = "text_artifact_id", nullable = false, columnDefinition = "text")
    private String textArtifactId;

    @Column(name = "summary_analysis_id", columnDefinition = "text")
    private String summaryAnalysisId;

    @Column(name = "quote", nullable = false, columnDefinition = "text")
    private String quote;

    @Column(name = "start_offset", nullable = false, columnDefinition = "bigint")
    private long startOffset;

    @Column(name = "end_offset", nullable = false, columnDefinition = "bigint")
    private long endOffset;

    @Column(name = "offset_unit", nullable = false, columnDefinition = "text")
    private String offsetUnit;

    @Column(name = "input_kind", nullable = false, columnDefinition = "text")
    private String inputKind;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "raw_locator_ids", nullable = false, columnDefinition = "jsonb")
    private List<String> rawLocatorIds;

    @Column(name = "quote_verified", columnDefinition = "boolean")
    private Boolean quoteVerified;

    @Column(name = "verification_artifact_id", columnDefinition = "text")
    private String verificationArtifactId;

    @Column(name = "verified_at", columnDefinition = "timestamptz")
    private Instant verifiedAt;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    protected Evidence() {
    }
}
