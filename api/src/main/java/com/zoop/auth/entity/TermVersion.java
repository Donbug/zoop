package com.zoop.auth.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

@Entity
@Table(name = "term_versions")
@IdClass(TermVersionId.class)
public class TermVersion {
    @Id
    @Column(name = "term_id", nullable = false, columnDefinition = "text")
    private String termId;

    @Id
    @Column(name = "version", nullable = false, columnDefinition = "text")
    private String version;

    @Column(name = "title_snapshot", nullable = false, columnDefinition = "text")
    private String titleSnapshot;

    @Column(name = "required_snapshot", nullable = false)
    private boolean requiredSnapshot;

    @Column(name = "body", nullable = false, columnDefinition = "text")
    private String body;

    @Column(name = "approved_at", nullable = false, columnDefinition = "timestamptz")
    private Instant approvedAt;

    @Column(name = "effective_at", nullable = false, columnDefinition = "timestamptz")
    private Instant effectiveAt;

    @Column(name = "retired_at", columnDefinition = "timestamptz")
    private Instant retiredAt;

    protected TermVersion() {
    }
}
