package com.zoop.auth.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "terms")
public class Term {
    @Id
    @Column(name = "id", nullable = false, columnDefinition = "text")
    private String id;

    @Column(name = "title", nullable = false, columnDefinition = "text")
    private String title;

    @Column(name = "required", nullable = false)
    private boolean required;

    @Column(name = "created_at", nullable = false, columnDefinition = "timestamptz")
    private Instant createdAt;

    @Column(name = "retired_at", columnDefinition = "timestamptz")
    private Instant retiredAt;

    protected Term() {
    }
}
